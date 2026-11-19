# Similar-paper search — developer context

"Does a paper like this already exist?" The user writes or pastes an abstract (also one for a paper they
wish existed), the text is embedded with the model of the stored vectors, and the nearest papers of the
library and, when the optional feed is on, of the feed come back with their cosine score.

Code: `backend/services/similar_search.py`, `backend/routers/similar.py`, `backend/tools/similarity_tools.py`,
`frontend/src/pages/SimilarSearch.tsx`, `frontend/src/api/similar.ts`, `frontend/src/components/similar/`.
Tests: `backend/tests/test_similar_*.py`, `frontend/src/pages/SimilarSearch.test.tsx`,
`frontend/src/components/nav/NavBar.similar.test.tsx`. User guide: `docs/user-guide/similar-search.md`.
It sits on the vector store (`.specs/019_vector_store.md`) and the feed (`.specs/018_paper_feed.md`).

## Service (`services/similar_search.py`)

```python
search_by_text(user, text, k=10, scope="both", since=None, min_score=0.0, include_stubs=False,
               *, follow=False, full_text=False, driver=None) -> dict
search_by_paper(user, paper_id, k=10, scope="both", since=None, min_score=0.0, include_stubs=False,
                *, follow=False, full_text=False, driver=None) -> dict
```

| Argument | Rule |
|---|---|
| `text` | stripped; 20 to 20,000 characters, else `InvalidRequest` (HTTP 422) |
| `k` | 1 to 50 |
| `scope` | `library`, `feed` or `both`. `feed` while the feed is off raises `FeedDisabled` (HTTP 404); `both` then silently means `library`, and the feed directory and namespace are not touched |
| `since` | `YYYY-MM-DD` (the date part of a timestamp is accepted). Feed: `published >= since` (a store filter). Library: the paper's `year >= since.year` (papers have a year, not a date); papers without a year are left out when `since` is given |
| `min_score` | cosine floor, -1 to 1, applied before hydration (default 0 drops everything orthogonal or worse) |
| `include_stubs` | reference stubs (tag `from-references`) are left out unless true |
| `follow` | the MCP server: stores are opened read-only (below) |
| `full_text` | adds `abstract` (up to 3,000 characters) to each hit; the page needs it for "use as the query", a tool result does not |

### Embedding

`services.conferences.embedder.embed_search_text(text) -> (vector, mode)`:

* a text of **more than 24 words** (`QUERY_MAX_WORDS`) is a *document*: `embed_document` embeds it as stored
  papers are embedded, with the model's document prefix (none for bge, `passage: ` for e5) and **no**
  retrieval instruction, cut at `DOC_MAX_LENGTH` = 256 tokens, the limit the library index and the feed use for
  title + abstract, so that the text lands where a paper like it would;
* a **short phrase** keeps the old behaviour: `embed_query` (retrieval instruction, 512 tokens). `mode` is
  `"query"`.

A request path never loads the model: when the backend's model is not loaded (and `PM_EMBED_URL` is empty)
the answer is `available: false`. A process without the model (the MCP server, `PM_EMBED_URL` set by
`mcp_server.py`) posts to `POST /conferences/embed`. The route got an optional `document` flag
(`{"text", "document": true}`): the text is embedded as a document, 256 tokens. Without the flag the route
is what it was (the text as given, 512 tokens), so an older client or backend keeps working. A backend that
cannot answer (404, 503, timeout, another model) makes the caller load the model locally, as for queries.

### Library hits

1. The `library` namespace is read as the process sees it: `semantic.peek()` in the backend, a follower
   (`get_store("library", create=False, follow=True)`, after the one-time legacy migration) in the MCP server.
2. **Over-fetch.** `OVERFETCH` (5) x k vectors are read, then hydrated from Neo4j **with
   `db.queries.visibility.paper_visibility_clause`**, so a paper the user may not see never leaves the
   service; stubs and the `since` year are applied in the same pass. If fewer than k survive and the store may
   hold more, the read grows 4x (up to `FETCH_CAP` = 1,000 vectors) and repeats. The visibility clause reads
   the request user, so the service sets the `user` argument as the request user for the duration of the
   search; the argument is authoritative.
3. Hydration is one parameterised query per round (`p.id IN $ids`): title, year, venue, DOI, arXiv id,
   abstract (else the cleaned summary), rating, bookmark, reading status, up to 8 authors, stub flag.

A library hit: `source: "library"`, `id`, `title`, `authors`, `year`, `venue`, `doi`, `arxiv_id`, `url` (the app's
`/paper/<id>` page under `FRONTEND_URL`), `score`, `snippet` (the first 300 characters on one line, `…` when cut),
`in_library: true`, `library_paper_id`, `my_label: null`, `rating`, `bookmarked`, `reading_status`,
`reference_stub`. Rating, bookmark and reading status are stored once per paper, as everywhere in the app.

### Feed hits

Only with `services.feed.config.enabled()`. The `feed` namespace gives the nearest candidate ids, the candidate
table gives title, authors, abstract, published date, URL, DOI. `in_library` and `library_paper_id` come from the
feed's own matching (`services.feed.library.match_candidate`, shared with the digest: arXiv id or DOI, then
title) against **the papers this user may see**, so a paper that sits only in another user's project reads as
not in the library. `my_label` is the requesting user's own label (1, -1, 0) or null; other users' labels are
never read into the result. A feed hit has `source: "feed"`, `feed_source` (arxiv, biorxiv, medrxiv),
`categories`, `published`.

In the backend the feed is read through the shared `FeedStore` (`by_ids`, `labels`). In the MCP server
(`follow=True`) it is read without creating anything: the `feed` namespace in follower mode and the candidate
and label tables through a read-only SQLite connection to `<PAPER_FEED_DIR>/feed.sqlite`. The MCP process
therefore needs the same `VECTOR_STORE_DIR`, `PAPER_FEED` and `PAPER_FEED_DIR` as the backend; with `PAPER_FEED`
unset there it sees the feed as off.

### Merge and result

Hits of both namespaces are merged by score (scores of one model are comparable across namespaces) and cut to k.

```json
{"available": true, "reason": null, "scope": "both", "mode": "document", "k": 10, "total": 7,
 "hits": [ ... ], "skipped": {"feed": "no feed papers have been embedded yet"}, "warnings": []}
```

`mode` is `document`, `query` (a short phrase) or `paper`. `search_by_paper` uses the stored vector of the
paper (read from the library namespace; a paper not indexed yet is embedded from title + abstract as a
document), leaves the paper itself out of the library hits and drops the feed's copy of it, and raises
`PaperNotFound` (HTTP 404) when the paper does not exist **or the user may not see it**.

**Never raises for an index that cannot be searched.** The answer is
`{"available": false, "reason": "...", "hits": [], "total": 0, "skipped": {...}}` (HTTP 200) when: semantic
search is off (`LIBRARY_SEMANTIC=false`), the library index is missing, empty (still building) or stale (another
`EMBED_MODEL`; being rebuilt), the feed namespace is missing, empty or stale (for `scope=feed`), the embedding
model is not loaded yet, or embedding fails. With `scope=both`, one namespace that is down is named in
`skipped` and the other still answers; `available` is false only when nothing can be searched. A library
index that is still being filled (backend process) adds a line to `warnings`.

## HTTP (`routers/similar.py`)

A new router, so `routers/search.py` is unchanged. Mounted in `main.py`; login required (the global
`RequireLoginMiddleware` and `Depends(get_current_user)`); `/search` is already proxied by nginx.

| Method | Path | Body or query | Notes |
|---|---|---|---|
| `POST` | `/search/similar` | `{text, k=10, scope="both", since?, min_score=0, include_stubs=false}` | 422 for a bad body, 404 for `scope=feed` with the feed off |
| `GET` | `/search/similar/{paper_id}` | `?k=&scope=&since=&min_score=&include_stubs=` | 404 for a paper that does not exist or is not visible |

Both are plain `def` routes (CPU-bound embedding runs in the threadpool) and return hits with `abstract`.

## MCP (`tools/similarity_tools.py`)

```
find_similar_papers(text: str, scope: str = "both", k: int = 10, since: str = "", min_score: float = 0.0) -> JSON
papers_like(paper_id: str, scope: str = "both", k: int = 10) -> JSON
```

Registered next to the other tool modules in `mcp_server.py`; results are compact JSON (`tools/_compact.py`
`json_tool`): per hit `title`, `url`, `score`, `source`, `in_library`, `id`, `authors` (three, then "et al."),
`year`, `snippet`, plus `library_paper_id`, `published`, `my_label` for feed hits and `venue`, `reading_status`
for library hits; empty fields are left out. `k` and `min_score` are clamped, not rejected. An invalid argument,
a missing feed or a paper that is not visible gives `{"error": "..."}`; an unavailable index gives
`{"available": false, "reason": "..."}`; any other failure (database down, no backend) gives
`{"error": "similarity search failed (<ErrorType>); is the backend running?"}`, never a stack trace. The two
tool definitions add about 1,100 characters to the budget every chat pays (`test_mcp_lean.py`, ceiling raised
from 18,500 to 19,500).

## Frontend

`/similar` (`pages/SimilarSearch.tsx`, lazily loaded), entry **Similar papers** in the Explore menu
(`navConfig.ts`). Not gated: the page works without the feed. The "Search in" toggle (Library / Feed / Both) is
shown only when `useFeatures()` says the feed is on; without it the request says `scope: "library"`.

* textarea (placeholder "Paste or write an abstract: title and a paragraph work best", character counter,
  Search disabled below 20 and above 20,000 characters), "Published since" date, result count (5 to 50);
* a result row (`components/similar/SimilarRow.tsx`): similarity bar (`role="meter"`) and score, a Library or Feed
  badge, an "In your library" badge on feed hits that are already in it, the title (library: the paper page;
  feed: the external URL in a new tab), authors, year or date, an expandable abstract, **Add to library** on
  feed hits not in the library (the same `POST /feed/{id}/add` as the feed page), and **Use this paper as the
  query**, which puts title + abstract into the textarea, without searching, so the text can be edited;
* states: nothing searched yet, searching, `available: false` ("The index is not ready for this search", the
  reason, Try again), no hits, notes for `skipped` and `warnings`, an error with Retry.

## Limits

* Quality is the embedding model's (bge-small by default) and the library's abstracts. A paper with only a title
  (many reference stubs) embeds poorly; stubs are hidden by default for that reason.
* The text is cut at 256 tokens (about 1,000 characters): the start of a long text decides the vector.
* Cosine scores are only comparable within one model; they are not probabilities. As a rule of thumb for
  bge-small, below about 0.6 is a weak match.
* `since` is coarse for library papers (year only).
