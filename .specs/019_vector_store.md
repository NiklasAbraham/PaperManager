# Vector store — developer context

One place for every embedding index of the app. Before it, the library's search index was one
`.npy` file rewritten as a whole, the feed's candidate vectors were SQLite blobs loaded in full, and
nothing recorded which model had produced a vector, so switching the embedding model would have mixed
two vector spaces silently. Now each index is a *namespace* of a small store that records its model
and refuses to mix.

Code: `backend/services/vectorstore/`. Tests: `backend/tests/test_vectorstore_*.py`.

## Shape

```
services/vectorstore/
  __init__.py       public names; usage example in the docstring
  model_config.py   ModelSpec + current(): the ONE place for EMBED_MODEL, dimension, pooling, prefixes
  base.py           VectorStore interface, Manifest, filters, GenerationalStore (CURRENT, manifest,
                    writer lock, rebuild/swap, compaction, backend conversion)
  exact.py          ExactGen: memory-mapped float32 file + SQLite, numpy search (default, no dependency)
  lance_store.py    LanceGen: optional LanceDB backend (VECTOR_STORE=lance)
  registry.py       get_store(namespace), vector_dir(), backend_name(), ExactStore / LanceStore
  migrate.py        one-time migration of emb.npy + meta.json and of the feed's embedding blobs
  similar.py        find_similar(): one query over several namespaces (library + feed)
```

Bulk switch tooling (prepared generations, adoption, rollback) is in `backend/scripts/vectors_*.py` and
`embed_bulk.py`; see "Bulk re-embedding elsewhere, adoption, rollback" below.

Namespaces in use: `library` (library_search/semantic.py), `feed` (candidate vectors) and `feed_library`
(the feed's cache of library vectors the search index lacks). The conference explorer keeps its own
float16 files; it only reads the model name and dimension from `model_config` (`current_conference()`).

## Interface (`VectorStore`)

| Call | Meaning |
|---|---|
| `upsert(ids, vectors, metadata=None)` | insert or replace by id; vectors are unit length (a vector whose norm is off by more than 1e-3 is normalised; unit vectors are stored bit-identical); a repeated id in one batch keeps the last |
| `delete(ids) -> int` | |
| `get(ids) -> {id: (vector, metadata)}` | |
| `metadata(ids=None) -> {id: metadata}` | without reading any vector |
| `search(query_vector, k=10, filter=None) -> [(id, score, metadata)]` | cosine, best first; `Hit` is a `NamedTuple` |
| `count()`, `ids()`, `all_vectors(filter=None)` | `all_vectors` is `(ids, matrix)` in insertion order |
| `manifest()`, `is_stale()`, `state()` | `missing`, `ready` or `stale` |
| `begin_rebuild(spec=None)` | see Rebuild |
| `compact()`, `convert_backend()`, `close()` | |

Metadata is a small dict. Filterable fields: `kind`, `source` (strings), `published` (date), `year`
(int, derived from `published` when absent), `added_at` (UTC timestamp); dates and timestamps are
normalised to `YYYY-MM-DD` and `YYYY-MM-DDTHH:MM:SSZ`. Other JSON-able keys ride along (the library
stores the text `hash` there) but cannot be filtered on; to make a field filterable add it to
`FILTER_FIELDS` in `base.py` and to both backends.

A filter is a dict, all keys ANDed: `{"kind": "paper"}`, `{"source": ["arxiv", "biorxiv"]}`,
`{"year": {"gte": 2020, "lt": 2025}}` (ranges on `year`, `published`, `added_at`), `{"id": [...]}`,
`{"exclude_id": [...]}`. Unknown keys and operators raise `ValueError`; rows without a value never match
a range.

## Manifest, stale, rebuild

`<root>/<namespace>/<generation>/manifest.json` holds `backend`, `model`, `dim`, `pooling`, `query_prefix`,
`doc_prefix`, `text_format`, `generation`, `created_at`, `updated_at`, `count`. `<root>/<namespace>/CURRENT`
names the live generation and is replaced atomically (temp file + rename).

A store is **stale** when its manifest's *space key* differs from the configured one:
`(model, dim, pooling, doc_prefix, text_format)`. The query prefix is not part of it. `TEXT_FORMAT` in
`model_config.py` versions how a paper's text is built (`semantic.paper_text`); bump it when that recipe
changes. A stale store refuses `upsert`, `delete`, `search`, `get` and `all_vectors`
(`StaleStoreError`); `count`, `ids`, `metadata` and `manifest` still answer.

`begin_rebuild(spec)` returns a `Rebuild` that fills a **new generation** next to the live one
(`upsert(...)`, then `commit()`; `abort()` or leaving a `with` block uncommitted throws it away). `commit()`
writes the new manifest, then flips `CURRENT`, then swaps the in-memory pointer. A search that started
before the swap finishes on the old generation; every search sees exactly one generation, never both. The
old generation's files are removed 60 s later (`RETIRE_GRACE_SECONDS`) and by the next writer start, except when the
swap changed the model and `VECTOR_STORE_KEEP_GENERATIONS` keeps it for a rollback (below). Writes
to the live generation while a rebuild runs are not carried over; the owner serialises (the semantic sync
lock; a stale store refuses writes anyway).

Owners and what they do when stale (before the rebuild, each first tries `adopt_matching`, see Bulk re-embedding):

* semantic index (`library`): `sync()` rebuilds from the Neo4j texts in the background thread; until the
  swap `query()` returns nothing and the search falls back to lexical, as while the first build runs;
  `status()["indexed"]` reads 0.
* feed (`feed`, `feed_library`): the refresh thread re-embeds the stored candidate texts
  (`FeedStore.rebuild_embeddings`) and the library texts (`rebuild_library_embeddings`); the digest sees no
  vectors meanwhile.

## Exact backend (default)

Per generation: `vectors.f32` (row-major float32, memory-mapped, capacity grows by 1.5x) and `meta.sqlite`
(`items(row, id, live, kind, source, published, year, added_at, extra)`). Vectors are only ever appended: a
replaced vector goes to a new row and the old row is marked dead, so a reader never sees a half-written
vector. The filterable columns are also numpy arrays (about 19 bytes per row); a filter is a vectorised
mask. Search scores the matrix in 32,768-row chunks with one matrix-vector product each (contiguous slices
when most rows match, a gather when few do), keeps a running top-k and reads ids and metadata from SQLite
for the winners only. Dead rows are compacted into a fresh generation when there are at least 1,000 and
more than half the live count.

Crash safety: a write puts the vectors in new rows and `flush()`es the map *before* the SQLite transaction
(WAL) commits; a crash leaves unreferenced rows that the next write overwrites. A truncated vector file or
missing files read as an empty store (`state() == "missing"`) and the next writer starts a clean generation.
A writer takes an exclusive `flock` on `<namespace>/LOCK` for its lifetime; a second writing process gets
`StoreLockedError` (so run one writing backend process per `VECTOR_STORE_DIR`; the semantic sync logs the error and retries). A process that only reads (the MCP server) opens the store with `follow=True`: it never
writes and reloads within about a second when the writer commits or swaps.

Measured on 8 CPU threads, 200,000 x 384 random unit vectors (`test_vectorstore_perf.py`): top-10 in about
15 ms (median, warm page cache; 45 ms in a first cold run), 28 ms with a two-field filter. Memory beyond the
page cache is the numpy columns only.

## Lance backend (optional)

`VECTOR_STORE=lance` and `pip install lancedb` (not in `requirements.txt`; install it into the image or
environment you run). Without the package the exact backend is used and a warning is logged once. Same
interface; one LanceDB table per generation; filters are pushed down as a SQL `where` with
`prefilter=True` (LanceDB takes no bind parameters, so values are validated or quote-escaped in
`lance_store.where_sql`); above `VECTOR_STORE_LANCE_INDEX_MIN` rows (default 50,000) an `IVF_HNSW_SQ`
cosine index is built and rebuilt when the table doubles; below it LanceDB scans, which is exact. An
existing namespace keeps the backend named in its manifest; `store.convert_backend()` (called by the
semantic sync and the feed) copies it into the configured one without re-embedding. `ids()` and
`all_vectors()` order is whatever LanceDB scans (the exact backend returns insertion order).

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `VECTOR_STORE` | `exact` | `exact` or `lance` |
| `VECTOR_STORE_DIR` | `/data/vectors` | root; falls back to a temporary directory when not writable |
| `VECTOR_STORE_LEGACY_EXPORT` | `1` | keep rewriting `emb.npy` + `meta.json` after a sync that changed something (the topic map reads them); `0` stops it |
| `VECTOR_STORE_LANCE_INDEX_MIN` | `50000` | rows above which the lance backend builds an ANN index |
| `EMBED_MODEL` | `BAAI/bge-small-en-v1.5` | embedding model (the old `CONFERENCE_EMBED_MODEL` still works) |
| `EMBED_DIM`, `EMBED_POOLING`, `EMBED_QUERY_PREFIX`, `EMBED_DOC_PREFIX` | from the model | needed only for a model that is not in `model_config.KNOWN`, or to override |
| `CONFERENCE_EMBED_MODEL` | empty | the conference explorer's model, read *first* by `model_config.current_conference()`; `EMBED_MODEL` only if it is empty. Another model than `EMBED_MODEL` takes `CONFERENCE_EMBED_DIM`, `_POOLING`, `_QUERY_PREFIX`, `_DOC_PREFIX` when not in `KNOWN` |
| `VECTOR_STORE_KEEP_GENERATIONS` | `2` | generations kept per namespace after a swap that changes the model, the live one included (`1`: none), see Bulk re-embedding |

`model_config.KNOWN` lists dimension, pooling and prefixes for a few bge, e5, MiniLM, MPNet and SPECTER2
models and the scientific-text `J0nasW/sciembed-full`; anything else needs `EMBED_DIM`. Empty variables count as unset. The embedder
(`services/conferences/embedder.py`) takes model, dimension, pooling and prefixes from `model_config`. It has two
roles: *library* (`embed`, `embed_query`, `embed_document`, `ready`; `EMBED_MODEL`: library search, feed, similar
papers) and *conference* (`conference_embed`, `conference_embed_query`, `conference_ready`;
`CONFERENCE_EMBED_MODEL` first, `EMBED_MODEL` if empty). Loaded models are cached per model id (`_models`), so two
roles naming one model share it. With neither variable set both roles are the default model, as before. The
explorer's own saved vectors are not versioned: when its model changes its datasets must be rebuilt, and until
then `store.load` leaves their vectors out (keyword search only) instead of failing on a dimension mismatch; set
`CONFERENCE_EMBED_MODEL` to the old model to keep them while the library moves on. `POST /conferences/embed` takes
`role` (`library` default, `conference`) so the MCP server asks for the right model.

## Bulk re-embedding elsewhere, adoption, rollback

Switching `EMBED_MODEL` with nothing prepared starts the background CPU rebuild described above. For a big library
the bulk is embedded on any machine with a GPU instead; user guide: `docs/user-guide/switching-the-embedding-model.md`.

```
scripts/vectors_export.py   backend env: spec.json + <namespace>.jsonl {id, text, hash, meta} for library, feed, feed_library
scripts/embed_bulk.py       GPU machine, torch + transformers + numpy only: <namespace>.npy + .ids.json + .done.json
scripts/vectors_import.py   backend env: checks, CPU sanity sample, writes a PREPARED generation per namespace
scripts/vectors_rollback.py backend stopped: swap back to the kept generation, print the env to restore
```

* **Texts**: the export reads through `semantic._fetch_texts` (every `Paper`, no per-user visibility: an operator
  tool, like the sync thread), `feed.pipeline._candidate_text` and `FeedStore.all_candidates()`. `feed_library` is
  what the feed would cache itself: library papers the search index will not hold (none while `LIBRARY_SEMANTIC` is
  on). The export directory is refused inside a git repository or the backend directory and created `0700`.
* **`embed_bulk.embed_texts` reproduces `embedder.embed`**: document prefix, then `" "` for an empty text, padding +
  truncation at `max_length` (256), CLS or mean pooling over the attention mask, L2 normalisation, float32 out; it adds
  longest-first batching, halving on CUDA OOM, float16 on CUDA (pooling in float32; a NaN run is repeated in fp32).
  `test_bulk_embed_embed.py` asserts equal output (< 1e-5) on a tiny random ModernBERT. Keep the two in step.
* **Prepared generations**: `store.begin_prepare(spec)` fills a directory `p######` (not `g######`, so no GC and no
  name race with the writer) and `commit()` writes its manifest plus a `PREPARED` marker. It needs no writer lock and
  works in `follow=True`, so `vectors_import.py` runs next to the live backend; the live generation, `CURRENT` and
  readers are untouched. One prepared generation per namespace: committing another replaces it. `store.prepared()`,
  `store.discard_prepared()`.
* **Adoption** (`store.adopt_matching(spec=None)`): when the live generation is missing, stale or empty and a finished
  generation with the configured space key exists, make it live (a prepared one is renamed to the next `g######` and
  its manifest rewritten; then `CURRENT` flips like a rebuild commit). Prepared generations are tried before kept ones.
  Called on start by `semantic._load` and `sync` (which then also rewrites the legacy `emb.npy`/`meta.json`) and by
  `FeedStore.vectors()` / `library_vectors()` (which drops vectors of candidates purged since the export). Never in
  follow mode; if another process holds the writer lock it logs and returns None; any other failure falls back to
  the rebuild. After adoption the normal sync compares text hashes (the import stores the export's) and embeds only
  new or changed papers.
* **Kept generations**: a swap that changes the space key (adoption, rollback, a CPU rebuild for another model) marks
  the generation it replaces `RETAINED` (marker file) when `VECTOR_STORE_KEEP_GENERATIONS` > 1; `_gc` and `_reap`
  skip marked directories and `_prune_retained` drops the oldest beyond `keep - 1`. Compaction and backend conversion
  keep nothing. `store.retained()`, `store.rollback()` (writer lock; activates the newest kept generation and keeps the
  current one in its place, so it undoes itself). Setting the old model again adopts the kept generation without the
  script.
* Tests: `test_bulk_embed_export.py`, `_embed.py` (also the ModernBERT load and the `KNOWN` entry), `_import.py`,
  `_adopt.py` (store, library sync, feed, rollback script), `_conference.py` (the role split).

## Migration (zero downtime, no re-embedding)

`migrate.py`, once per namespace (when neither `<namespace>/CURRENT` nor `<namespace>/MIGRATED.json`
exists). The old files and columns are read, never changed or deleted; the marker records the source,
count, model and time and stops a deliberately emptied namespace from being refilled with old data.

* `library` from `<LIBRARY_SEARCH_DIR>/emb.npy` + `meta.json`, only when `meta.json` names the configured
  model, the shape matches and the hashes line up. Run by the semantic thread at startup (`_load`), or by the
  MCP server's `ensure_loaded()` if it starts first. Until it has run, `query()` returns nothing (lexical
  search), exactly as before the file was loaded.
* `feed` from `candidate.emb` and `feed_library` from `library_emb`, on the first vector access of a
  `FeedStore`, only when the configured model is the one the embedder used before (`CONFERENCE_EMBED_MODEL`
  or the default); blobs carry no model name, so with another `EMBED_MODEL` they are skipped and the
  candidates are embedded again from their stored text.

After migration the semantic index and the feed read and write only through the store; the feed's
`without_embedding()` is "candidates whose id is not in the `feed` namespace". The sync still writes
`emb.npy` + `meta.json` after a change (flag above), so the topic map and a downgrade keep working. The export writes the whole matrix, so on a very large library switch it off once the topic map is not needed.

## Calling the store from search code

```python
from services.vectorstore import get_store
from services.vectorstore.similar import find_similar_text

library = get_store("library", create=False)          # None until built; never creates anything
if library is not None and not library.is_stale():
    hits = library.search(query_vector, k=20, filter={"kind": "paper"})   # [(id, cosine, metadata)]

# "find papers like this abstract" over library and feed candidates, newest candidates only:
result = find_similar_text(abstract, k=10, filter={"published": {"gte": "2026-01-01"}})
result.hits        # [SimilarHit(namespace, id, score, metadata)], best first
result.skipped     # {"feed": "stale"} for namespaces that are missing, empty or stale
```

`find_similar` / `find_similar_text` are the plain building block (no user, no visibility). The visibility-aware
search behind `POST /search/similar`, the page `/similar` and the MCP tools is `services/similar_search.py`
(`.specs/020_similar_search.md`).

## Tests

`test_vectorstore_core.py` (interface on both backends against a brute-force reference, filters, metadata,
normalisation, persistence), `_exact.py` (crash safety, damaged files, compaction, threads, writer lock,
follower), `_rebuild.py` (stale, rebuild, atomic swap under concurrent readers, backend conversion),
`_migrate.py` (library and feed migration with identical top-k, semantic sync and model switch, feed model
switch), `_config.py`, `_lance.py`, `_similar.py`, `_perf.py`. The lance cases skip with a reason when
`lancedb` is not importable; to run them without installing it into the environment:
`pip install --target <dir> lancedb` and `PM_VEC_LANCE_PATH=<dir> pytest ...`.
`tests/conftest.py` gives every test its own `VECTOR_STORE_DIR`.
