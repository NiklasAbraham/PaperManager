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
| `GET` | `/search` | Full-text + filtered search |
| `GET` | `/graph` | Graph data for visualisation |
| `POST` | `/graph/cypher` | Custom Cypher → graph nodes + links |
| `GET` | `/stats` | Library statistics |

### `/search` Query Parameters

| Parameter | Type | Description |
| --------- | ---- | ----------- |
| `q` | string | Full-text query |
| `tag` | string | Filter by tag name |
| `topic` | string | Filter by topic name |
| `project_id` | string | Filter by project ID |
| `person_id` | string | Filter by person ID |
| `year_min` | int | Minimum publication year |
| `year_max` | int | Maximum publication year |
| `reading_status` | string | Filter by reading status |

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
| `GET` | `/knowledge-chat/conversations` | List all conversations |
| `GET` | `/knowledge-chat/conversations/{id}/messages` | Messages in a conversation |
| `POST` | `/knowledge-chat/conversations/{id}/compact` | Compact conversation history |
| `DELETE` | `/knowledge-chat/conversations/{id}` | Delete conversation |

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

SSE event types: `progress`, `token`, `done`, `error`.

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

| Method | Path | Description |
| ------ | ---- | ----------- |
| `GET` | `/discover/search` | Search arXiv + S2 + PubMed (`?q=&limit=`) |
| `POST` | `/discover/add` | Add a search result to the library |

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

## Cypher, Export, Backfill

| Method | Path | Description |
| ------ | ---- | ----------- |
| `GET` | `/cypher/schema` | Live Neo4j schema (labels, types, keys) |
| `POST` | `/cypher/run` | Run raw Cypher (max 500 rows) |
| `POST` | `/cypher/assist` | Ollama generates Cypher from natural language |
| `DELETE` | `/cypher/nodes/{id}` | Delete any node by ID |
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
