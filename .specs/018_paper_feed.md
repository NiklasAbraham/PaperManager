# Paper feed — developer context

User guide: `docs/user-guide/paper-feed.md`. This file is the how.

An **optional** daily digest of new preprints, ranked for each user by a small classifier trained on
what that user already keeps in their library. The method follows Scholar Inbox (Flicke et al.,
2025, arXiv 2504.08385): embed title + abstract, train a logistic regression on the user's positive
and negative signals plus a sample of random negatives, rank new papers by predicted relevance.
PaperManager has no connection to the Scholar Inbox service; this is a local re-implementation.

## Optional by design (hard requirements)

- **Off by default.** `PAPER_FEED=false`. When off: no thread starts, no schema is touched, no
  directory is created, no model is loaded, no network call is made, the nav item is hidden and
  every `/feed/*` route except `GET /feed/status` answers `404`. `GET /feed/status` always answers
  `{"enabled": false}`. A test proves each of these.
- **No new dependencies.** numpy, torch, transformers and httpx are already installed. The
  classifier is plain numpy (no scikit-learn). Do not edit `requirements.txt`.
- **No GPU needed.** Embedding uses the same bge-small CPU embedder as the conference explorer
  and library search (`services.conferences.embedder`). A few hundred papers a day take seconds.
- **No private data in the repository.** Nothing instance-specific in code, docs, specs, tests
  or fixtures: no real names, e-mail addresses, hosts, tokens, paths outside the repo, paper
  titles from a real library or real keyword lists. Test data is synthetic. Defaults are neutral.

## Shape

```
backend/services/feed/
  __init__.py
  config.py        enabled(), FEED_DIR, instance env settings, per-user FeedConfig dataclass
  store.py         SQLite sidecar <FEED_DIR>/feed.sqlite: candidates, embeddings, labels, config, runs
  sources.py       fetch_arxiv(categories, since), fetch_biorxiv(server, since) -> Candidate rows
  model.py         numpy logistic regression (fit, predict), training-set builder, offline AUC
  library.py       the user's visible papers with their signals, library vectors, embedding cache sync
  pipeline.py      refresh(): fetch -> dedupe -> embed -> store; daemon thread, start_background()
  ranking.py       digest(user, ...): training set, per-user model cache, scoring, neighbours ("why")
backend/routers/feed.py        /feed/* HTTP API
backend/tests/test_feed_*.py
frontend/src/pages/Feed.tsx    /feed
frontend/src/components/feed/  FeedSetup, FeedRow, FeedStatus
frontend/src/api/feed.ts, lib/features.ts   typed API; the optional-features flag the nav reads
docs/user-guide/paper-feed.md  user documentation (add to mkdocs nav)
```

## Storage

SQLite, not Neo4j: candidates are ephemeral and numerous, and the Aura free tier caps nodes.
`<FEED_DIR>` is `PAPER_FEED_DIR` or `/data/feed` with the same writable-fallback logic as
`library_search/semantic.py::data_dir`. Tables (create lazily, only when enabled):

- `candidate(id TEXT PK, source, ext_id, title, authors, abstract, published, url, doi, categories,
  fetched_at, emb BLOB)` — `id` = `arxiv:<id>` / `biorxiv:<doi>` / `medrxiv:<doi>` (medRxiv keeps its own prefix); unique on (source, ext_id). Ids may contain `/`.
  `emb` is 384 float32 (unit vector).
- `label(user, candidate_id, value INTEGER, created_at)` — value 1 (up) / -1 (down) / 0 (dismissed).
  Primary key (user, candidate_id).
- `config(user PK, json)` — per-user FeedConfig.
- `run(id, started_at, finished_at, source, fetched, new, embedded, error)` — history for Status.
- `fetch_state(key PK, since)` — when each source key (`arxiv:<category>`, `biorxiv`, `medrxiv`) last
  succeeded; the next fetch starts one day before it (`OVERLAP`), a new key reaches back by the longest
  digest window. A failed key is not advanced, so it is retried whole. (Added: needed so a category chosen
  later is back-filled and a failure loses nothing.)
- `library_emb(paper_id PK, hash, emb)` — vectors of library papers the library search index lacks (see Model).

Candidates older than `PAPER_FEED_RETENTION_DAYS` (default 30) are deleted unless a user rated
them. Papers added to the library are linked by `library_paper_id` at read time, not stored.

## Instance settings (env; documented in `.env.example` with neutral defaults, commented out)

| Variable | Default | Meaning |
|---|---|---|
| `PAPER_FEED` | `false` | master switch |
| `PAPER_FEED_DIR` | `/data/feed` | sidecar directory |
| `PAPER_FEED_INTERVAL` | `21600` | seconds between refreshes (6 h) |
| `PAPER_FEED_RETENTION_DAYS` | `30` | candidate retention |
| `PAPER_FEED_MAX_PER_REFRESH` | `2000` | cap on papers fetched per source and refresh |
| `PAPER_FEED_CONTACT` | empty | optional contact string appended to the User-Agent |

## Per-user config (`PUT /feed/config`, edited on the Feed page)

`sources` (`arxiv`, `biorxiv`, `medrxiv`), `arxiv_categories` (list, e.g. `["cs.LG"]`; **empty by
default**, the page asks the user to choose; a refresh fetches only the union of all users'
categories), `digest_days` (1–14, default 3), `min_score` (default 0). The union rule keeps the
fetch small: nothing is fetched when no user has chosen a category.

## Sources (`sources.py`)

- arXiv: `export.arxiv.org/api/query`, `search_query=cat:<c>`, `sortBy=submittedDate`, paged
  100 at a time, at least 3 s between requests (arXiv's rule), stop at `since`. Parse the Atom feed
  with `xml.etree` (the code in `services/literature_search.py` is a model; reuse its helpers where
  they fit, do not edit that file's behaviour).
- bioRxiv / medRxiv: `https://api.biorxiv.org/details/<server>/<from>/<to>/<cursor>` (JSON,
  100 per page). Only first versions (`version == "1"`) become candidates, so a revised old paper does not
  reappear as new. There is no category filter: the whole server is fetched (capped), the ranking sorts it.
- Every request: User-Agent `PaperManager-feed` (+ `PAPER_FEED_CONTACT` if set), timeout 30 s, three tries
  with doubling backoff on network errors, 429 and 5xx. The existing `_get` helper hard-codes its own
  User-Agent, so `sources.py` has its own small `_http_get` (it reuses only `_ssl_verify`).
- A failing source is logged and recorded in `run.error`; it never stops the other source or the
  backend.

## Model (`model.py`)

Embeddings: library papers come from `services.library_search.semantic` (the existing store;
read it, do not duplicate the embedding work; if it is disabled or empty, embed the needed
library papers with the same embedder and cache them in the feed store); candidates are embedded
at refresh time. Same model, same 384-dim space.

A bookmark outranks a low rating (the user kept the paper). Rating 0 or none is "unrated". The first
reading of the weak-positive row ("rating 3, read, highlights") was taken as an and; the table now says
what the code does: read-and-highlighted papers count even without a rating, rating 3 needs one more sign.
`S` is relative to the positives, not an absolute 1.0: an absolute total of 1.0 spread over 5000 rows would
make the random negatives irrelevant next to positives of weight 1.0 each; relative, the classes balance.

Per user, the training set is built only from papers that user may see
(`db.queries.visibility.paper_visibility_clause`; read how ratings, bookmarks and reading status
are stored per user and be conservative: if a signal is global, use it only for the single-user
case as the existing code does). Result: rating, bookmark and reading status are properties of the Paper
node, not of a user, so `library.visible_papers` returns a `single_user` flag (at most one `User` node) and
a `mine` flag per paper (`(:User)-[:ADDED]->(p)` for this user). Shared signals count for every visible
paper when `single_user`, otherwise only for `mine`. Feed labels are always per user:

| Signal | Label | Weight |
|---|---|---|
| rating >= 4, or bookmarked | positive | 1.0 |
| status `read` with highlights, or rating 3 together with `read` or highlights | positive | 0.5 |
| rating <= 2 | negative | 1.0 |
| feed thumbs-down or dismissed | negative | 1.0 |
| feed thumbs-up | positive | 1.0 |
| random sample (<= 5000) of stored candidates not labelled | negative | together `S` x the total positive weight (`S` = 1.0, `RANDOM_NEGATIVE_SHARE`), each `S * W+ / n_random` |

Fit: L2-regularised logistic regression with class-weighted cross-entropy, full-batch L-BFGS
(`scipy.optimize` is available through the existing install; if importing it fails fall back to
plain gradient descent) or numpy Newton steps. Features are the unit embeddings (384 dims, no PCA
needed). Standardise nothing; add a bias. Regularisation `C` default 1.0.

Library vectors: the library search index first (`library.semantic_snapshot`, read-only), then the feed
store's `library_emb`. The refresh thread (never a request) embeds the papers the index lacks, and only when
somebody chose a source, so an instance with the feed on but nothing chosen loads no model.

Cold start: fewer than `10` positives -> no classifier; rank by the maximum cosine similarity to
any positive (or, with zero positives, by newest first) and say so in the response
(`mode: "similarity" | "classifier" | "newest"`).

Quality: when there are >= 30 positives, hold out the 20 % most recently added, report ROC AUC of
held-out positives vs. random candidates as `quality.auc` in `GET /feed/status` (no number is a
promise; the UI shows it with a short caveat). The model is cached per user in memory and refit
when the set of signals changes (a hash of the positive and negative keys with their weights) or after
24 h. A fit is about a second at the largest sizes: it runs in the digest call when the training set has at
most `FIT_MAX_ROWS` (6000) rows; a larger set is served by similarity ranking while a one-off `feed-fit`
thread fits it (the request cannot hand its visibility context to the refresh thread, so the training set is
built in the request and only the fit moves). The quality fit (second fit without the hold-out) doubles the
cost, so it runs in the same place.

Neighbours ("why this paper"): the three library papers with highest cosine similarity to the
candidate, as `{paper_id, title, similarity}` (titles come from Neo4j with the visibility clause).

## API (`routers/feed.py`; every route requires login like the other routers)

| Route | Notes |
|---|---|
| `GET /feed/status` | `{enabled, state, last_refresh, next_refresh, candidates, embedded, mode, positives, quality, error}` (`mode`, `positives`, `quality` are what this user's last digest used, null before); works when disabled |
| `GET /feed` | query: `days`, `skip`, `limit`, `include_rated`, `source`; returns ranked items with `score`, `mode`, `neighbours`, `in_library`, `library_paper_id`, `my_label` |
| `POST /feed/{id}/rate` | body `{"value": 1 \| -1}` |
| `POST /feed/{id}/dismiss` | label 0 |
| `POST /feed/{id}/add` | body `{"project_id"?: str}`; ingests through the existing URL ingest path (`routers.papers.ingest_from_url`, see `routers/discover.py` for the call), links to the project, records a thumbs-up |
| `GET /feed/config`, `PUT /feed/config` | per-user config |
| `DELETE /feed/{id}/label` | removes the user's label (added: the UI toggles) |
| `POST /feed/refresh` | starts a refresh now (admin or the only user, else 403); 202, 409 while running |

`GET /feed` also returns `total`, `days`, `positives`, `quality` and `configured` (false until the user chose
a category or a bioRxiv / medRxiv source; the page shows the setup panel then). Hidden by default: anything
the user labelled, including dismissed. Ids in URLs are URL-encoded and routed with Starlette's `path`
converter (`/feed/{id:path}/rate`), because bioRxiv DOIs and old arXiv ids contain `/`. Items already in the library (match on `arxiv_id` or DOI, using the
logic in `services/library_lookup.py`) are flagged `in_library` and ranked last unless
`include_rated`.

## Frontend

`pages/Feed.tsx` at `/feed`, lazily loaded in `App.tsx`. The nav item appears only when
`GET /feed/status` says `enabled` (fetched once, cached; follow the pattern of the other nav items
and the `lib/instance` helpers). First visit with no categories shows the setup panel (source
checkboxes, a category field with a few neutral example chips such as `cs.LG`, `cs.CV`, `q-bio.BM`).
Rows: title, authors, date, score bar, "why" (neighbour titles), abstract expand, buttons Add,
Add to project, thumbs up/down, dismiss. Status strip: last refresh, candidates, mode, AUC.
Style per `docs/style-guide.md`. Vitest tests in the style of `Suggestions.test.tsx`.

## Wiring outside the feed's own files

`main.py` mounts the router always (so `/feed/status` can answer) and starts the thread only when
`PAPER_FEED` is on; the router's other routes depend on `require_enabled` (404 when off).
`frontend/nginx.conf` proxies `/feed` and lists it in the `$spa_page` map (the existing route-guard test
requires both for every API prefix). `docker-compose.selfhost.yml` points `PAPER_FEED_DIR` at the data volume
so labels survive a container rebuild; `docker-compose.example.yml` passes the three main variables through.
The nav item comes from `lib/features.ts` (one `GET /feed/status` after login, never before).

## Optional extra (last, skip if time is short, off by default)

**Not implemented** in the first version (no setting is read, nothing is generated). `PAPER_FEED_EXPLAIN=false`: when true and the instance has a fast model configured, the top 10
digest items get a one-sentence reason generated by the fast model from the candidate abstract and
its three neighbour titles (`services/ai.py` has the fast-model helper; use the same pattern as
`services/tag_suggester.py`). Cached in the store; failures are silent.

## Tests (backend/tests, no network, no real Neo4j beyond what other tests use)

- disabled: status disabled, other routes 404, `start_background()` starts no thread, no directory
  created, `sources` never called.
- sources: parsers on synthetic Atom/JSON strings; paging and `since` stop; failing source isolated.
- store: candidate upsert, retention delete (rated kept), labels, config.
- model: on synthetic clustered embeddings the classifier ranks held-out in-cluster points above
  out-of-cluster; cold start modes; AUC computed.
- pipeline: refresh with patched sources and a fake embedder yields the expected rows; union of
  categories; dedupe against the library with a patched lookup.
- router: ranking, rate, dismiss, add (patched ingest), config validation (category pattern
  `^[a-z\-]+(\.[A-Za-z\-]+)?$`, max 30), per-user isolation of labels.
- frontend: setup panel, ranked rows, rate/add calls, nav hidden when disabled.
