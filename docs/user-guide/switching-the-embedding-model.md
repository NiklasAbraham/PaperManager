# Switching the embedding model

PaperManager turns every paper's title and abstract into a vector (an *embedding*). Library search, the
[paper feed](paper-feed.md) and [similar papers](similar-search.md) all compare those vectors. The default
model is small (`BAAI/bge-small-en-v1.5`, 384 numbers per paper) and runs on the backend's CPU. A larger
model, for example a scientific one such as `J0nasW/sciembed-full` (ModernBERT-base, 768 numbers, MIT licence),
can place related papers closer together.

**For the operator of the server.** This page is not about using the app but about changing what it runs on.

## Why this needs a procedure

Vectors of two models cannot be compared, so a switch means embedding the whole library again: one text per
paper, plus the feed's stored candidates and the feed's cache of library vectors. If you only change
`EMBED_MODEL` and restart, the backend does exactly that on its own CPU, in the background. For a library of
about ten thousand papers and a base-sized model that takes hours, and search answers by keywords meanwhile.

The tools described here move that bulk job to **any machine with a CUDA GPU** (a few minutes) and leave the
everyday work, embedding the handful of papers that arrive each day, with the backend's CPU and the same model.
The new vectors are prepared next to the live ones, the backend adopts them when it restarts with the new
setting, and the old ones are kept so that you can go back.

## The five steps

All commands start in the backend's environment (below: the Docker Compose service named `backend`; use
`python scripts/...` directly from the `backend/` folder if you run it without Docker). The export folder holds
the text of your whole library, so it must not live in a git checkout. `vectors_export.py` refuses such a path.

**1. Export the texts** (in the backend environment):

```bash
docker compose exec backend python scripts/vectors_export.py \
    --out /data/vector_export --model J0nasW/sciembed-full
docker compose cp backend:/data/vector_export ~/vector_export
```

This reads the library (and, when `PAPER_FEED=true`, the feed's candidates) and writes `spec.json`
(model, dimension, pooling, prefixes, text format, 256-token limit, counts) and one `<namespace>.jsonl` file per
vector set: `library`, `feed`, `feed_library`. A model that PaperManager does not list needs
`--dim N` (and `--pooling cls|mean`, `--doc-prefix ...`) as well. Nothing is written to the databases.

The export is made with direct database access and **no per-user filtering**, like the sync thread that builds
the search index: the vector index is shared by every user of the instance and only the final result lists are
filtered by who may see what. Delete the folder when you are done.

**2. Copy it to a GPU machine**:

```bash
scp -r ~/vector_export user@gpu-host:~/
scp backend/scripts/embed_bulk.py user@gpu-host:~/
```

**3. Embed there.** `embed_bulk.py` is one file that needs only `torch` (with CUDA), `transformers` (4.48 or newer
for ModernBERT models) and `numpy`; no PaperManager code, no database, no key:

```bash
python embed_bulk.py ~/vector_export --device cuda
```

It embeds in float16 with a batch size that halves when the GPU runs out of memory, prints progress, and writes
`<namespace>.npy` (float32, unit length) and `<namespace>.ids.json` next to the export. Run again after an
interruption: finished namespaces are skipped. `--offline --model /path/to/model` uses a local copy of the
model; `--device cpu` works too, only slowly. It truncates at 256 tokens, pools and normalises exactly like the
backend's CPU embedder (a test keeps the two equal), so the vectors the backend makes later for new papers sit in
the same space.

**4. Copy the results back and import them**:

```bash
scp user@gpu-host:~/vector_export/*.npy user@gpu-host:~/vector_export/*.json ~/vector_export/
docker compose cp ~/vector_export backend:/data/
docker compose exec backend python scripts/vectors_import.py /data/vector_export
```

The import checks each namespace (dimension, one vector per id, no NaN, unit length, the vectors belong to the
exported texts) and then **re-embeds 20 random texts on the backend's CPU** with the real embedder, requiring a
mean cosine of at least 0.98 to the imported vectors (float16 on the GPU against float32 here). It needs the
model on the backend; if it cannot load it, it says so and imports unverified; `--skip-check` skips the
check on purpose. The vectors are stored as a **prepared generation**: not live, no lock on the running
backend, nothing about the current index changes and search keeps working. It prints the ids the live index holds
that the import lacks (papers added since the export), which the normal sync embeds later.
`vectors_import.py DIR --discard` throws a prepared generation away; importing again replaces it.

**5. Switch.** Set the model in the backend's environment (`.env`) and restart:

```env
EMBED_MODEL=J0nasW/sciembed-full
CONFERENCE_EMBED_MODEL=BAAI/bge-small-en-v1.5
```

`J0nasW/sciembed-full` is in the built-in list (768 dimensions, mean pooling, no prefixes). For another model
add `EMBED_DIM`, `EMBED_POOLING` and the prefixes the import printed. On start the backend finds the prepared
generation for exactly this setting, **adopts it instead of re-embedding**, and the sync embeds only papers that
are missing or whose text changed since the export. The old generation stays on disk as the rollback target.

`CONFERENCE_EMBED_MODEL` is optional but recommended: the [conference explorer](conferences.md) keeps its own
saved vectors, built with the old model. It reads `CONFERENCE_EMBED_MODEL` first and `EMBED_MODEL` only when that
is empty, so setting it to the old model keeps the explorer's topic search working while the library moves on.
Both models are then loaded in the backend (about 130 MB and 600 MB). Without it the explorer follows
`EMBED_MODEL`, its vectors no longer fit, and its topic search falls back to keywords until its datasets are
rebuilt.

## Going back

The generation a model switch replaces is kept: `VECTOR_STORE_KEEP_GENERATIONS` (default `2`) counts the live
generation, so one older one is kept per vector set (`3` keeps two, `1` keeps none). Two ways back:

* Set `EMBED_MODEL` (and the other settings) back to the old values and restart. The backend finds the kept
  generation of that setting and adopts it instead of rebuilding; papers added since are embedded by the sync.
* Or stop the backend and run `python scripts/vectors_rollback.py` (`--status` lists what is live, kept and
  prepared). It swaps the kept generations back and prints the exact settings to put back into `.env`. The
  environment variables **must** then be set back before the restart: with the new model still configured the
  backend would see the restored generation as outdated and adopt the other one again. A rollback can be undone
  by running the script again.

## What happens to search and the feed

* **Search is never mixed.** Each vector set records the model it was built with. While it does not match the
  configured model (for instance after an `EMBED_MODEL` change that nothing was prepared for), library search
  and similar papers answer by keywords and the feed sees no vectors, until a matching generation is adopted or
  the rebuild has finished. A query is always embedded with the model of the vectors it is compared with.
* **The feed retrains by itself.** Its classifier is fitted from vectors in memory and is not stored: after the
  switch the next ranking uses the new vectors. Candidates and cached library vectors that arrived after the
  export are embedded in the next refresh; candidates purged since the export are dropped from the adopted set.
* **Rebuilds still work.** A start with a new `EMBED_MODEL` and no prepared generation behaves as before: a new
  generation is built in the background on the CPU and swapped in when complete (the old one is kept for a
  rollback there as well).
* **Disk.** A kept generation costs `papers x dimension x 4` bytes plus a small database: about 17 MB for
  ten thousand papers at 384 dimensions, 31 MB at 768.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `EMBED_MODEL` | `BAAI/bge-small-en-v1.5` | Model of library search, the feed and similar papers |
| `EMBED_DIM`, `EMBED_POOLING`, `EMBED_QUERY_PREFIX`, `EMBED_DOC_PREFIX` | from the model | Only for a model that is not in the built-in list, or to override it |
| `CONFERENCE_EMBED_MODEL` | empty | The explorer's model; read first, `EMBED_MODEL` only when empty. A model other than `EMBED_MODEL` takes `CONFERENCE_EMBED_DIM`, `_POOLING`, `_QUERY_PREFIX`, `_DOC_PREFIX` when it is not in the built-in list |
| `VECTOR_STORE_KEEP_GENERATIONS` | `2` | Generations kept per vector set after a model switch, the live one included |

Models are loaded without `trust_remote_code`: a model that needs custom code from its repository is not
supported here. Developer notes are in `.specs/019_vector_store.md`.
