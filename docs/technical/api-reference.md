# API Reference

All endpoints are served from `http://localhost:8000`. Interactive API docs (Swagger UI) are available at `http://localhost:8000/docs`.

---

## Papers

### Core CRUD

| Method | Path | Description |
| ------ | ---- | ----------- |
| `GET` | `/papers` | List papers (`?skip=&limit=`) |
| `POST` | `/papers` | Create paper (manual, no PDF) |
| `GET` | `/papers/{id}` | Get paper detail |
| `PATCH` | `/papers/{id}` | Update paper fields |
| `DELETE` | `/papers/{id}` | Delete paper + Drive file + figures |

### Ingestion

| Method | Path | Description |
| ------ | ---- | ----------- |
| `POST` | `/papers/parse` | Extract metadata from PDF (preview, no save) |
| `GET` | `/papers/check-duplicate` | Check for duplicate (`?doi=` or `?title=`) |
| `POST` | `/papers/upload` | Upload PDF (multipart/form-data) |
| `POST` | `/papers/from-url` | Ingest from URL/DOI/arXiv (metadata only) |
| `POST` | `/papers/from-url-full` | Ingest from URL + download PDF if available |
| `POST` | `/papers/bulk-import` | Bulk import (SSE stream) |

### PDF & Chat

| Method | Path | Description |
| ------ | ---- | ----------- |
| `GET` | `/papers/{id}/pdf` | Stream PDF from Google Drive |
| `POST` | `/papers/{id}/chat` | Chat with paper (single-paper Q&A) |
| `POST` | `/papers/{id}/regenerate-summary` | Re-run Claude summary on stored raw_text |
| `POST` | `/papers/{id}/reextract-abstract` | Re-extract abstract (regex → Claude Haiku) |

### Notes

| Method | Path | Description |
| ------ | ---- | ----------- |
| `GET` | `/papers/{id}/note` | Get markdown note |
| `PUT` | `/papers/{id}/note` | Create or update note |

### References

| Method | Path | Description |
| ------ | ---- | ----------- |
| `GET` | `/papers/{id}/extract-references` | Extract references (no save, preview) |
| `GET` | `/papers/{id}/ai-extract-references` | Force Claude Haiku reference extraction |
| `POST` | `/papers/{id}/references` | Save extracted reference list |
| `GET` | `/papers/{id}/references` | List outgoing + incoming citations |

### Tags & Topics

| Method | Path | Description |
| ------ | ---- | ----------- |
| `POST` | `/papers/{id}/tags` | Add tag to paper |
| `DELETE` | `/papers/{id}/tags/{name}` | Remove tag from paper |
| `POST` | `/papers/{id}/topics` | Add topic to paper |
| `DELETE` | `/papers/{id}/topics/{name}` | Remove topic from paper |
| `POST` | `/papers/{id}/topics/suggest` | AI topic suggestion for paper |

### People Relationships

| Method | Path | Description |
| ------ | ---- | ----------- |
| `POST` | `/papers/{id}/authors` | Link author (Person) to paper |
| `DELETE` | `/papers/{id}/authors/{person_id}` | Unlink author |
| `POST` | `/papers/{id}/involves` | Link person with a role |
| `DELETE` | `/papers/{id}/involves/{person_id}` | Unlink person |

### Figures

| Method | Path | Description |
| ------ | ---- | ----------- |
| `GET` | `/papers/{id}/figures` | List extracted figures |
| `GET` | `/papers/{id}/figures/{fig_id}/image` | Get figure image (PNG bytes) |
| `POST` | `/papers/{id}/figures/extract` | Extract figures from PDF |
| `POST` | `/papers/{id}/figures/{fig_id}/chat` | Vision chat about a figure |

### Annotations

| Method | Path | Description |
| ------ | ---- | ----------- |
| `GET` | `/papers/{id}/annotations` | List PDF annotations |
| `POST` | `/papers/{id}/annotations` | Create annotation (highlight + note) |
| `PATCH` | `/papers/{id}/annotations/{ann_id}` | Update annotation note/color |
| `DELETE` | `/papers/{id}/annotations/{ann_id}` | Delete annotation |

### Claims

| Method | Path | Description |
| ------ | ---- | ----------- |
| `GET` | `/papers/{id}/claims` | List extracted claims |
| `POST` | `/papers/{id}/claims/extract` | Re-run claim extraction (`?model=`) |

### Chapters (books / lecture decks)

| Method | Path | Description |
| ------ | ---- | ----------- |
| `GET` | `/papers/{id}/chapters` | List chapters |
| `POST` | `/papers/{id}/chapters/detect` | Detect + create chapters (Docling → regex → AI) |
| `GET` | `/papers/{id}/chapters/{ch_id}` | Get single chapter |
| `GET` | `/papers/{id}/chapters/{ch_id}/pdf` | Get chapter as PDF slice |
| `POST` | `/papers/{id}/chapters/{ch_id}/summarize` | Re-generate chapter summary |
| `POST` | `/papers/{id}/chapters/{ch_id}/chat` | Chat with chapter text |

---

## People

| Method | Path | Description |
| ------ | ---- | ----------- |
| `GET` | `/people` | List all people |
| `POST` | `/people` | Create person |
| `POST` | `/people/get-or-create` | Get or create by name |
| `GET` | `/people/{id}` | Person detail + papers + specialties |
| `PATCH` | `/people/{id}` | Update name / affiliation |
| `DELETE` | `/people/{id}` | Delete person |
| `POST` | `/people/{id}/specialties` | Add research specialty (Topic) |
| `PATCH` | `/people/{id}/track` | Set tracked status (`{"tracked": true/false}`) |
| `GET` | `/people/{id}/new-papers` | Preview new papers not yet in library |
| `POST` | `/author-tracker/check-all` | Check all tracked authors + auto-import |

---

## Tags

| Method | Path | Description |
| ------ | ---- | ----------- |
| `GET` | `/tags` | List tags with paper counts |
| `POST` | `/tags` | Create tag |
| `DELETE` | `/tags/{name}` | Delete tag |
| `POST` | `/tags/suggest` | AI tag suggestion (Ollama) |
| `GET` | `/tags/{name}/papers` | Papers with this tag |

---

## Topics

| Method | Path | Description |
| ------ | ---- | ----------- |
| `GET` | `/topics` | List topics with paper counts |
| `POST` | `/topics` | Create topic |
| `DELETE` | `/topics/{name}` | Delete topic |
| `PATCH` | `/topics/{name}` | Rename topic (moves all relationships) |
| `GET` | `/topics/{name}/papers` | Papers about this topic |
| `POST` | `/topics/{a}/related/{b}` | Mark two topics as related |

---

## Projects

| Method | Path | Description |
| ------ | ---- | ----------- |
| `GET` | `/projects` | List projects |
| `POST` | `/projects` | Create project |
| `GET` | `/projects/{id}` | Project detail + paper list |
| `PATCH` | `/projects/{id}` | Update project |
| `DELETE` | `/projects/{id}` | Delete project |
| `POST` | `/projects/{id}/papers` | Add paper to project |
| `DELETE` | `/projects/{id}/papers/{paper_id}` | Remove paper from project |
| `POST` | `/projects/{a}/related/{b}` | Link two related projects |

---

## Venues

| Method | Path | Description |
| ------ | ---- | ----------- |
| `GET` | `/venues` | List venues with paper counts (`?min_count=&q=`) |
| `GET` | `/venues/{name}/papers` | Papers from this venue |

---

## Search, Graph, Stats

| Method | Path | Description |
| ------ | ---- | ----------- |
| `GET` | `/search` | Ranked library search (titles, authors, topics, tags, venue, abstracts, notes, highlights, claims, full text; optional semantic blend), or filters only without `q` |
| `GET` | `/search/suggest` | Type-ahead: `papers` (title), `authors`, `topics`, `tags`, `projects` for a prefix (`?q=&limit=5`); each entity with its paper count |
| `GET` | `/search/status` | Semantic index state (`state`, `indexed`, `done`/`todo` while building) and the full-text indexes' state |
| `GET` | `/graph` | Graph data for visualisation |
| `POST` | `/graph/query` | Admin only. One Cypher run returning `columns`, `rows` (max 500), `row_count`, `truncated`, `counters`, `nodes`, `links` (graph view, max 5,000 nodes) and `took_ms`. Body `{query, read_only}`; `read_only` defaults to `true` (managed read transaction, writes are rejected) |
| `POST` | `/graph/cypher` | Admin only. Legacy: custom Cypher → graph nodes + links (the Graph page uses `/graph/query`) |
| `GET` | `/stats` | Library statistics |

### `/search` Query Parameters

| Parameter | Type | Description |
| --------- | ---- | ----------- |
| `q` | string | Query: words (prefix, one typo for 5+ letters), `"phrases"`, `word*`, a DOI or arXiv id. Case and accents are ignored |
| `tag` | string | Filter by tag name (case-insensitive) |
| `topic` | string | Filter by topic name (case-insensitive) |
| `project_id` | string | Filter by project ID |
| `person_id` | string | Filter by person ID (authored or involved) |
| `venue` | string | Filter by venue (case-insensitive) |
| `year_min` | int | Minimum publication year |
| `year_max` | int | Maximum publication year |
| `reading_status` | string | Filter by reading status |
| `bookmarked` | bool | Only bookmarked papers |
| `added_after` | string | Added on or after `YYYY-MM-DD` or an ISO datetime; a bad value returns 422 |
| `added_before` | string | Added before `YYYY-MM-DD` (that day included) or an ISO datetime; 422 on a bad value |
| `has_pdf`, `has_text`, `has_note`, `has_highlights` | bool | PDF stored, full text extracted, a note exists, at least one highlight |
| `document_type` | string | `paper`, `book`, `lecture_deck` or `news_article` |
| `rating_min` | int | Minimum star rating, 1–5 |
| `include_references` | bool | Include reference stubs (tag `from-references`); default `true`, ranked below library papers |
| `mode` | string | `lexical` (default), `hybrid` (lexical + embedding similarity, reciprocal-rank fusion) or `semantic`; falls back to lexical while the embedding index is not ready |
| `sort` | string | `relevance` (default with `q`), `date_desc` (default without), `date_asc`, `year_desc`, `year_asc`, `title_asc`, `rating_desc`, `citations_desc`, `updated_desc` |
| `snippets` | int | Passages per hit, 0–6 (default 2) |
| `skip`, `limit` | int | Paging after ranking; `limit` 1–2000 (default 20) |

Response: `{results, total, mode, relaxed, semantic, failed_sources, took_ms}`. `total` counts
every hit, not just the page. Each hit is the paper plus `score`, `matched_in` (coarse, e.g.
`note+paper`), `matched_fields` (`doi`, `title`, `author`, `topic`, `tag`, `venue`, `abstract`,
`summary`, `note`, `highlight`, `claim`, `fulltext`, `semantic`), `matches` (matched author /
topic / tag / venue names), `snippets` (`{field, text, marks, page?}`), `title_marks`, `authors`,
`is_reference`, `similarity` (hybrid/semantic), `text_chars`, `has_note`, `highlight_count`,
`projects`. `marks` are `[start, end)` offsets in code points. `relaxed: true` means no paper
contained every word and partial matches are shown. Ranking, weights and indexes:
`.specs/012_search.md`. Ranked results are cached in-process for 60 s per user (any non-GET request
clears the cache; `LIBRARY_SEARCH_CACHE=0` turns it off).

### `/graph` Query Parameters

| Parameter | Value | Description |
| --------- | ----- | ----------- |
| `mode` | `full` | All node types (up to 500 nodes) |
| `mode` | `papers` | Papers, People, Topics only |
| `mode` | `paper` | Single paper neighbourhood (`&id={paper_id}`) |

---

## Knowledge Chat

| Method | Path | Description |
| ------ | ---- | ----------- |
| `POST` | `/knowledge-chat/stream` | Multi-paper chat (SSE streaming) |
| `POST` | `/knowledge-chat/stop` | Stop an answer that is still being written (`{user_message_id}`); the text so far is kept. Returns `{stopped}` |
| `GET` | `/knowledge-chat/conversations` | List all conversations |
| `GET` | `/knowledge-chat/conversations/{id}/messages` | Messages in a conversation, with the saved tool-call trace |
| `PATCH` | `/knowledge-chat/conversations/{id}` | Rename (`{title}`) |
| `POST` | `/knowledge-chat/conversations/{id}/compact` | Compact conversation history |
| `POST` | `/knowledge-chat/conversations/{id}/fork` | Fork a strand (`{keep, kind: "strand"\|"edit"}`) |
| `DELETE` | `/knowledge-chat/conversations/{id}` | Delete conversation |
| `POST` | `/knowledge-chat/messages/{id}/visualise` | Generate concept cards for an answer |
| `GET` | `/knowledge-chat/messages/{id}/concepts` | Concept cards and their state |
| `POST` | `/knowledge-chat/messages/{id}/concepts/{index}/repair` | Ask the model to fix a broken card (`{error}`) |
| `GET` | `/knowledge-chat/structures` | Structure data for a 3D card: `?pdb=`, `?afdb=`, `?ccd=` or `?pubchem=` |

### `/knowledge-chat/stream` Request Body

```json
{
  "message": "What are the key contributions of @tag:transformers papers?",
  "conversation_id": "optional-uuid",
  "model": "claude",
  "user_id": "optional-user-id"
}
```

Mention syntax: `@tag:name`, `@topic:name`, `@project:name`, `@paper:title`.

SSE event types: `conversation`, `context`, `step` (one tool call: its input, a preview of the result and
the papers, figures or pages it touched), `token`, `interim` (the model's short note between tool calls),
`suggestion` (a proposed improvement, see [Suggestions](#suggestions)), `done` and `error`. Tool steps are
saved with the answer, so reopening a conversation shows them again.

---

## Claims (library-wide)

| Method | Path | Description |
| ------ | ---- | ----------- |
| `GET` | `/claims/search` | Search claims across all papers (`?q=&limit=`) |

---

## Synthesis & Analysis

| Method | Path | Description |
| ------ | ---- | ----------- |
| `POST` | `/synthesis` | Cross-paper synthesis (`paper_ids`, `question`, `use_web`) |
| `POST` | `/research-gaps` | Research gap analysis for a topic / paper set |

---

## Blogs

| Method | Path | Description |
| ------ | ---- | ----------- |
| `GET` | `/blogs` | List registered blogs |
| `POST` | `/blogs` | Register a blog (auto-detects RSS feed) |
| `GET` | `/blogs/{id}` | Blog detail |
| `DELETE` | `/blogs/{id}` | Delete blog |
| `POST` | `/blogs/{id}/fetch` | Refresh posts from RSS feed |
| `GET` | `/blogs/{id}/posts` | List posts (`?status=&skip=&limit=`) |
| `GET` | `/blogs/posts/random` | Random post (`?status=unread`) |
| `GET` | `/blogs/posts/{post_id}` | Get single post (auto-imports content) |
| `PATCH` | `/blogs/posts/{post_id}` | Update post fields |
| `DELETE` | `/blogs/posts/{post_id}` | Delete post |
| `POST` | `/blogs/posts/{post_id}/summarize` | AI summarise a post |
| `POST` | `/blogs/posts/{post_id}/chat` | Chat with a blog post |
| `GET` | `/blogs/posts/{post_id}/note` | Get post note |
| `PUT` | `/blogs/posts/{post_id}/note` | Create/update post note |
| `POST` | `/blogs/posts/{post_id}/tags` | Tag a post |
| `DELETE` | `/blogs/posts/{post_id}/tags/{name}` | Untag a post |
| `GET` | `/blogs/posts/{post_id}/tags` | List tags for a post |
| `POST` | `/blogs/posts/{post_id}/people` | Link person to post |
| `DELETE` | `/blogs/posts/{post_id}/people/{person_id}` | Unlink person |
| `GET` | `/blogs/posts/{post_id}/people` | List people linked to post |
| `POST` | `/blogs/posts/{post_id}/projects/{project_id}` | Add post to project |
| `DELETE` | `/blogs/posts/{post_id}/projects/{project_id}` | Remove from project |

---

## Literature (external paper streaming)

| Method | Path | Description |
| ------ | ---- | ----------- |
| `POST` | `/literature/search` | Stream recent papers from arXiv / PubMed / bioRxiv (SSE) |
| `GET` | `/literature/keywords` | Get saved keyword list |
| `POST` | `/literature/keywords` | Update keyword list |

### `/literature/search` Request Body

```json
{
  "days": 7,
  "max_per_source": 100,
  "sources": ["arxiv", "pubmed", "biorxiv"],
  "project_id": "optional-project-id"
}
```

---

## Discover (external search)

The Discover page was folded into **Find papers** in the frontend (`/discover` redirects to `/literature?tab=search`); these endpoints remain.

| Method | Path | Description |
| ------ | ---- | ----------- |
| `GET` | `/discover/search` | Search arXiv + S2 + PubMed (`?q=&limit=`) |
| `POST` | `/discover/add` | Add a search result to the library |

---

## Conferences (conference explorer)

`{key}` is a conference-year (`neurips2026`) or a name (`ICML 2025`, `iclr` = latest).

| Method | Path | Description |
| ------ | ---- | ----------- |
| `GET` | `/conferences/catalog` | Every known conference-year with its build state, the area taxonomy, the default set |
| `GET` | `/conferences/search/query` | Across all loaded conferences (`?q=&kind=all\|paper\|author&series=&field=&year_min=&year_max=&limit=`): `papers` (`title` matches with `title_match`, `semantic` by meaning, `title_total`, `highlight`, `corrected`), `authors` (cards with papers per conference, institutions, `identities`; `highlight`, `corrected`), `suggested` tab, `ms`. Case-insensitive |
| `POST` | `/conferences/search/topic` | `{query, k=300, series?, field?, year_min?, year_max?, papers?}`: the k closest papers pooled over all loaded conferences (title vectors); `conferences` with `count` and `per_1k`, `trend` per series, pooled `academia` / `industry`, `areas`, `papers`, `threshold`, `skipped` |
| `POST` | `/conferences/embed` | `{"text"}` → `{"model", "dim", "vector"}`: the bge-small embedding of a text as given (the caller adds the query instruction), for MCP processes that do not load the model; 503 until it is loaded |
| `GET` | `/conferences/{key}/status` | Build state: `none`, `queued`, `fetching`, `normalising`, `embedding`, `ready`, `partial`, `unavailable`, `error` (+ `progress`) |
| `POST` | `/conferences/{key}/build` | Queue a download + index (also refreshes a loaded one) |
| `GET` | `/conferences/{key}/overview` | Counts, area mix, top universities and companies (409 while not loaded) |
| `GET` | `/conferences/{key}/institutions` | Ranked institutions (`?q=&sector=A\|I&area=&offset=&limit=`) |
| `GET` | `/conferences/{key}/institutions/{slug}` | One institution: rank, counts, area mix, collaborators, authors, papers |
| `POST` | `/conferences/{key}/topic` | `{query, k}`: the k closest papers, counted per institution, area mix, top papers |
| `GET` | `/conferences/{key}/papers/{pid}` | Abstract, authors with institutions, closest papers |
| `POST` | `/conferences/{key}/papers/{pid}/add` | Add to the library (`{project_id?}`); returns the existing paper on a title match |

---

## Merge (duplicate detection)

| Method | Path | Description |
| ------ | ---- | ----------- |
| `POST` | `/merge/scan` | Scan for near-duplicate papers (`?model=ollama\|claude`) |
| `POST` | `/merge/execute` | Merge a pair of duplicate papers |

---

## Users

| Method | Path | Description |
| ------ | ---- | ----------- |
| `GET` | `/users` | List users |
| `POST` | `/users/identify` | Get or create user by name |
| `DELETE` | `/users/{id}` | Delete user |
| `PATCH` | `/users/{id}/rename` | Rename user |
| `POST` | `/users/{id}/ask` | Search user's conversation history |

---

## Tokens (usage ledger)

All endpoints need a session. Admins see every user and may filter with `user=`; anyone else sees only their own
calls (`user` is ignored). See [Architecture](architecture.md#usage-ledger).

| Method | Path | Description |
| ------ | ---- | ----------- |
| `GET` | `/tokens/summary` | `?days=30` (1–366) `&user=&feature=&model=`. Totals, today, `by_day`, `by_week`, `by_feature`, `by_model`, `by_provider`, `by_user` (admins), `top_calls`, `top_papers`, `unknown_models`, `prices_as_of` |
| `GET` | `/tokens/calls` | Newest calls first: `?limit=100` (≤ 500) `&offset=&user=&feature=&model=&provider=&paper_id=&ok=&days=`. Returns `{calls, total}` |
| `GET` | `/tokens/prices` | The price table: `{as_of, litellm_free, models: [{prefix, input, output, cache_write, cache_read}]}` (USD per million tokens) |

---

## Reports

Reports are private to their owner; admins can read and delete all.

| Method | Path | Description |
| ------ | ---- | ----------- |
| `GET` | `/reports/options` | Available `models` (`fast`, `claude`, `claude-work`), `lengths` and `default_model` |
| `POST` | `/reports` | Start a report in the background (202). Body `{question?, project_id?, paper_ids?, length?: "short"\|"standard"\|"long", model?}`; 422 without a question and a project |
| `GET` | `/reports` | The caller's reports, newest first (`?all=true` for admins: everyone's) |
| `GET` | `/reports/{id}` | Report with `markdown`, progress `steps` and cited `papers` |
| `GET` | `/reports/{id}/export` | `?format=md` (default) or `html`; a file download |
| `POST` | `/reports/{id}/cancel` | Stop a queued or running report |
| `DELETE` | `/reports/{id}` | Delete (204) |

---

## Suggestions

| Method | Path | Description |
| ------ | ---- | ----------- |
| `GET` | `/suggestions` | `?status=&source=&sort=votes\|new`. Each item has `votes`, `voted`, `status`, `source` (`chat`, `user`, `report`) |
| `GET` | `/suggestions/counts` | Counts per status |
| `POST` | `/suggestions` | `{text (3–280), detail? (≤ 2000)}` (201) |
| `PATCH` | `/suggestions/{id}` | `{status?, text?, detail?}`; status: admin only; text and detail: author or admin |
| `POST` | `/suggestions/{id}/vote` | Toggle your vote |
| `DELETE` | `/suggestions/{id}` | Author or admin (204) |

---

## System health

| Method | Path | Description |
| ------ | ---- | ----------- |
| `GET` | `/system/health` | Admin only (403 otherwise). `?refresh=true` recomputes the cached checks. Returns `status` (`ok`, `degraded`, `error`), `checks`, `version`, `tokens_today`, `recent_errors`, `sweepers`, `audit` |
| `GET` | `/health` | Public load-balancer probe: `{status, neo4j}` |

---

## Cypher, Export, Backfill

| Method | Path | Description |
| ------ | ---- | ----------- |
| `GET` | `/cypher/schema` | Live Neo4j schema (labels, types, keys); used by the Graph page's query panel |
| `POST` | `/cypher/run` | Run raw Cypher (max 500 rows, no graph view, always writable); admin only. The Graph page uses `/graph/query` instead |
| `POST` | `/cypher/assist` | AI model generates Cypher from natural language |
| `DELETE` | `/cypher/nodes/{id}` | Delete any node by ID; admin only |
| `GET` | `/export/bibtex` | Download BibTeX for all papers |
| `POST` | `/backfill/topics` | Bulk AI topic assignment |
| `POST` | `/backfill/summary` | Bulk AI summarisation |
| `POST` | `/backfill/figures` | Bulk figure extraction |

---

## Utilities

| Method | Path | Description |
| ------ | ---- | ----------- |
| `GET` | `/health` | Health check — returns `{status, neo4j}` |
| `GET` | `/ollama/models` | List locally available Ollama model names |
| `GET` | `/stats` | Library statistics (counts, by_year, top_topics, recent) |

---

## Interactive API Docs

With the backend running, visit:

- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`
- **OpenAPI JSON**: `http://localhost:8000/openapi.json`
