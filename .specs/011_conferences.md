# Conference explorer — developer context

User guide: `docs/user-guide/conferences.md`. This file is the how.

## Shape

```
backend/services/conferences/
  catalog.py       Series + years + source per conference-year (key "neurips2026")
  sources.py       fetch(edition) -> rows in one shape (miniconf feed or Paper Copilot list)
  institutions.py  split_and_normalise(raw) -> [(canonical name, "A"|"I")], ALIASES table
  areas.py         AREAS taxonomy (24), prototypes(embed_fn), assign(emb, protos)
  embedder.py      embedding model via transformers on CPU (default bge-small-en-v1.5, set by EMBED_MODEL, see 019_vector_store.md); embed(texts), embed_query(text)
  store.py         build(key), worker queue, start_auto_build(), load(key) -> Dataset, queries
  search.py        one index over all loaded datasets: search_papers, search_authors, topic
backend/routers/conferences.py      /conferences/* HTTP API
backend/tools/conference_tools.py   MCP: list_conferences, conference_topic (one or "all"),
                                    conference_institution, conference_search_papers,
                                    conference_search_author
frontend/src/pages/Conferences.tsx  /conferences (landing + search all) and /conferences/:key
frontend/src/components/conferences/  AreaBar, PaperRow, InstitutionsView, InstitutionCard, TopicView,
                                      SearchAll
```

No Neo4j: conference data lives on disk, never as Paper nodes. Neo4j is touched only for the
library title match (visibility-filtered, cached 2 min per user) and "+ Library".

## Storage

`<CONFERENCE_DATA_DIR or /data/conferences>/<key>/`:

- `dataset.json`: meta + `papers` + `insts`. Paper rows use short keys: `id` (sha1 of the folded
  title, 10 hex), `t` title, `a` abstract, `au` author names, `ai` per-author institution indices,
  `i` unique institution indices, `ar` area index (-1 until indexed), `d` decision, `tr` track,
  `s` session(s), `u` conference page, `f` forum / OpenReview, `nt` the site's own topic, `kw`.
  Institution rows: `n` name, `s` sector, `p` papers, `f` fractional, `a` per-area counts, `r` rank,
  `slug`.
- `emb.npy`: float16, (papers, 384), unit rows, same order as `papers`.
- `emb_title.npy`: the same for the title alone, only when some paper has an abstract or
  keywords (otherwise `emb.npy` already is title-only and `Dataset.temb` is `emb`).
- `status.json`: `state` in none / queued / fetching / normalising / embedding / ready / partial /
  unavailable / error, plus `progress`, `message`, counts. A state left "building" by a restart is
  read back as ready / partial / none from the files present.
- `models/` (shared): the Hugging Face cache for the embedder.

`store.load` keeps up to `CONFERENCE_CACHE_MAX` (32) datasets in memory, keyed by the mtimes of
`dataset.json` and `emb_title.npy`, so a rebuild or a title backfill is picked up without a
restart. The cache must hold every loaded conference: cross-conference search uses all of them
on every query (nine conferences, 38,000 papers: about 250 MB resident).

## Build

One daemon thread drains a queue, one conference at a time (`request_build` is idempotent while
queued). `dataset.json` is written twice: after normalising (institution views work) and after
embedding (areas, semantic search). Text embedded per paper: `title. abstract`, or
`title. keywords` without an abstract; batches are sorted by length (padding dominates CPU time).
Area prototypes: mean of the area's phrases as "A research paper about {phrase}.".

`start_auto_build()` runs from the FastAPI lifespan: queues `CONFERENCES_DEFAULT` entries that are
missing / partial / failed, this year's ones older than `CONFERENCES_REFRESH_DAYS`, and this year's
"unavailable" ones (they may have been published since). `CONFERENCES_AUTO=false` turns it off.
It then queues `titles:<key>` items (`build_title_embeddings`, no status change) for datasets
built before `emb_title.npy` existed, and starts `search.warm()` in a thread: load every
dataset, build the search index (2 s for 38,000 papers and 83,000 author names) and the typo
tables, load the model. A search that meets a dataset without title vectors queues the same
backfill.

## Sources

- **miniconf**: `https://<host>/static/virtual/data/<conf>-<year>-orals-posters.json` (`results`,
  `count`, `next`). An oral is listed twice (poster + talk) and NeurIPS 2026 lists a paper once per
  city: rows are merged by folded title (not `paper_url`: some feeds reuse one OpenReview link),
  keeping the best decision and every session. When `next` points at the login-protected API the
  build keeps the first page, marks the dataset `partial` with `expected`, and adds the missing
  papers as title-only rows from `https://<host>/virtual/<year>/papers.html` (its `<noscript>`
  list), so topic search covers the conference.
- **Paper Copilot**: `raw.githubusercontent.com/papercopilot/paperlists/main/<dir>/<dir><year>.json`;
  large files are Git LFS pointers, fetched again from `media.githubusercontent.com`. Affiliations
  from `aff_unique_norm` + `aff_unique_index` (`"0+1;1"` = author 1 at institutions 0 and 1),
  falling back to raw `aff`. Statuses containing "reject" or "withdraw" are dropped.
- OpenReview's own API refuses anonymous clients (challenge page), so it is not a source.

## Maths

- Topic search: cosine similarity of the query vector to every paper (`emb @ q`), top-k, then
  per-institution counts over those k; ties broken by summed similarity.
- Areas: centre papers and prototypes on the conference's mean paper vector before the argmax.
  Without centring the most generic area (efficiency) took 21 % of NeurIPS 2026, 12 % after refinement
  (median paper–prototype cosine 0.80, median top-two margin 0.016); with it the largest area holds 7 %. Then two rounds of
  prototype := normalise(½ prototype + ½ mean of its papers) and reassign.
- Fractional counting: author = 1/n of the paper, split equally over the author's institutions.

## Search across conferences (`search.py`)

`search.index()` builds one `_Index` over `store.loaded_keys()` (every key with a
`dataset.json`, so a conference being refreshed stays searchable) and rebuilds it when
`store.load` returns a different `Dataset` object for any key. Filters (`series`, `field`,
`year_min`, `year_max`) are applied per query, not per index.

- **Titles**: folded words (`institutions.fold`, split on non-alphanumerics) -> postings of
  global paper ids. A query word matches exactly (1.0), as plural / singular (0.95), as a
  prefix if it is the last word (0.9), or at optimal-string-alignment distance 1 if it has
  five letters or more and is not itself a title word (0.8; symmetric-delete table built once).
  Stopwords are ignored unless the query is only stopwords. Candidates come from the rarest
  word's postings (the two rarest when one word may be missing). Tiers: whole title 4, title
  starts with the query 3, phrase 2.5, all words 2, all but one 1 (queries of 3+ words); then
  idf-weighted word coverage, then cosine. Semantic results exclude papers shown as title
  matches; unknown words are replaced by their most frequent one-edit neighbour before
  embedding, so a typo does not move the query vector. The response carries `highlight`
  (`words`: every folded form a query word matched; `prefixes`: words matched as prefixes),
  which the client marks in titles with React spans, and `corrected` when typo correction
  changed the query ("did you mean"). Queries are lowercased before embedding (bge-small's
  tokenizer lowercases too); `test_search_ignores_case` checks that case variants give
  identical papers, authors and topics.
- **Authors**: folded full name -> mentions `(paper id, author position)`; name words ->
  names. Every query word must match a name word: exact, prefix (initials, typing) or one edit.
  Score 100 for the full name in any order, 50 + 40 × mean weight otherwise, +5 when the
  surname is matched exactly; ties by paper count. A card counts institutions by `merge_key`
  across conferences and joins mentions that share an institution or a co-author
  (union-find); more than one component is reported as `identities`, a hint that one name
  covers several people.
- **Topic**: cosine of the query to `Dataset.temb` (title-only) of every selected conference,
  pooled; the k-th largest similarity is the threshold `τ`, and conference c's count is
  `|{j in c : s_j >= τ}|`, reported also per 1,000 of its papers. Institutions are pooled by
  `merge_key`; `of_own` divides by the institution's papers at the selected conferences.

### Why pooled top-k on title vectors

Measured on the nine default conferences (38,000 papers) for four queries, against the share of
titles containing a keyword (`protein`, `gaussian splat`, ...):

- **Raw cosine is not comparable across conferences.** A paper embedded as title + abstract
  sits 0.03–0.07 higher in cosine to any query than one embedded from its title (mean
  similarity to "diffusion models for protein structure": NeurIPS 2025 with abstracts 0.648,
  NeurIPS 2026 titles only 0.582). Pooling raw cosines gave NeurIPS 2025 24.4 papers per 1,000
  against 4.3 for NeurIPS 2026, while the keyword shares are 6.3 and 5.4.
- **Per-conference centring does not fix it.** Subtracting each conference's median similarity
  over-corrected (NeurIPS 2025 2.4, ICCV 2025 4.1 per 1,000 on "Gaussian splatting" against
  a keyword share of 35); z-scoring flattened real differences (ECCV 2026 0.4 per 1,000 on
  "video generation", keyword share 39).
- **Title-only vectors for every conference** put both NeurIPS years at the same mean (0.582)
  and the per-1,000 rates follow the keyword shares (video generation: ECCV / CVPR / ICCV 14–17,
  ML venues 4–7; Gaussian splatting: vision venues 16–22, ML venues 2–6). The cost is one extra
  title pass for conferences with abstracts or keywords (20–45 s each).
- **A pooled top-k instead of a fixed cosine threshold**: cosine levels differ between a short
  query with bge's retrieval instruction and a pasted abstract without it, so no fixed value
  works for both; the k-th similarity adapts to the query and is the same for every
  conference. Fixed top-k per conference would give every conference k papers and answer
  nothing.

## Routes

The API never uses a path a page uses: `/conferences/catalog` (not `/conferences`),
`/conferences/{key}/overview` (not `/conferences/{key}`) and `/conferences/search/query`
(the search page is `/conferences?q=`). `/search/...` routes are declared before the
`/{key}/...` routes: `POST /conferences/search/topic` would otherwise be the topic view of a
conference called "search". With equal paths the browser answers
the `fetch` from the cached page HTML. nginx sends `/conferences*` requests that ask for
`text/html` to the SPA and everything else to the backend.

## Tests

`backend/tests/test_conferences.py`: normaliser cases, both parsers on fixtures (monkeypatched
`_get_json`), counting / ranking / fractional on a hand-made dataset, topic search (semantic
with a stubbed `embed_query`, keyword fallback), area assignment on synthetic clusters, and
the endpoints; for the search, three hand-made conferences (abstracts with title vectors, titles
only, abstracts without title vectors): title tiers, plural / prefix / typo matching, filters,
author name forms and the identity split, pooled topic counts, trend and skipped conferences,
the title backfill and both endpoints. No network, no model, no Neo4j.
`frontend/src/pages/Conferences.test.tsx` covers the landing page, the overview, a topic query
from the URL, and the search box (author tab suggested from the URL, topic across
conferences, debounced typing).
