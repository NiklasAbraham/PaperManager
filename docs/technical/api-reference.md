# API Reference

All endpoints are served from `http://localhost:8000`. Interactive API docs (Swagger UI) are available at `http://localhost:8000/docs`.

---

## Papers

### Core CRUD

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/papers` | List papers (`?skip=&limit=`) |
| `POST` | `/papers` | Create paper (manual, no PDF) |
| `GET` | `/papers/{id}` | Get paper detail |
| `PATCH` | `/papers/{id}` | Update paper fields |
| `DELETE` | `/papers/{id}` | Delete paper + Drive file + figures |

### Ingestion

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/papers/parse` | Extract metadata from PDF (preview, no save) |
| `GET` | `/papers/check-duplicate` | Check for duplicate (`?doi=` or `?title=`) |
| `POST` | `/papers/upload` | Upload PDF (multipart/form-data) |
| `POST` | `/papers/from-url` | Ingest from URL/DOI/arXiv |
| `POST` | `/papers/bulk-import` | Bulk import (SSE stream) |

### PDF & Chat

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/papers/{id}/pdf` | Stream PDF from Google Drive |
| `POST` | `/papers/{id}/chat` | Chat with paper (single-paper Q&A) |

### Notes

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/papers/{id}/note` | Get markdown note |
| `PUT` | `/papers/{id}/note` | Create or update note |

### References

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/papers/{id}/extract-references` | Extract references (no save, preview) |
| `POST` | `/papers/{id}/references` | Save extracted reference list |
| `GET` | `/papers/{id}/references` | List outgoing + incoming citations |

### Tags & Topics

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/papers/{id}/tags` | Add tag to paper |
| `DELETE` | `/papers/{id}/tags/{name}` | Remove tag from paper |
| `POST` | `/papers/{id}/topics` | Add topic to paper |
| `DELETE` | `/papers/{id}/topics/{name}` | Remove topic from paper |
| `POST` | `/papers/{id}/topics/suggest` | AI topic suggestion for paper |

### People Relationships

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/papers/{id}/authors` | Link author (Person) to paper |
| `DELETE` | `/papers/{id}/authors/{person_id}` | Unlink author |
| `POST` | `/papers/{id}/involves` | Link person with a role |
| `DELETE` | `/papers/{id}/involves/{person_id}` | Unlink person |

### Figures

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/papers/{id}/figures` | List extracted figures |
| `GET` | `/papers/{id}/figures/{fig_id}/image` | Get figure image (PNG bytes) |
| `POST` | `/papers/{id}/figures/extract` | Extract figures from PDF |
| `POST` | `/papers/{id}/figures/{fig_id}/chat` | Vision chat about a figure |

---

## People

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/people` | List all people |
| `POST` | `/people` | Create person |
| `POST` | `/people/get-or-create` | Get or create by name |
| `GET` | `/people/{id}` | Person detail + papers + specialties |
| `PATCH` | `/people/{id}` | Update name / affiliation |
| `DELETE` | `/people/{id}` | Delete person |
| `POST` | `/people/{id}/specialties` | Add research specialty (Topic) |

---

## Tags

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/tags` | List tags with paper counts |
| `POST` | `/tags` | Create tag |
| `DELETE` | `/tags/{name}` | Delete tag |
| `POST` | `/tags/suggest` | AI tag suggestion (Ollama) |
| `GET` | `/tags/{name}/papers` | Papers with this tag |

---

## Topics

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/topics` | List topics with paper counts |
| `POST` | `/topics` | Create topic |
| `DELETE` | `/topics/{name}` | Delete topic |
| `PATCH` | `/topics/{name}` | Rename topic (moves all relationships) |
| `GET` | `/topics/{name}/papers` | Papers about this topic |
| `POST` | `/topics/{a}/related/{b}` | Mark two topics as related |

---

## Projects

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/projects` | List projects |
| `POST` | `/projects` | Create project |
| `GET` | `/projects/{id}` | Project detail + paper list |
| `PATCH` | `/projects/{id}` | Update project |
| `DELETE` | `/projects/{id}` | Delete project |
| `POST` | `/projects/{id}/papers` | Add paper to project |
| `DELETE` | `/projects/{id}/papers/{paper_id}` | Remove paper from project |
| `POST` | `/projects/{a}/related/{b}` | Link two related projects |

---

## Search, Graph, Stats

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/search` | Full-text + filtered search |
| `GET` | `/graph` | Graph data for visualisation |
| `POST` | `/graph/cypher` | Custom Cypher → graph nodes + links |
| `GET` | `/stats` | Library statistics |

### `/search` Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `q` | string | Full-text query |
| `tag` | string | Filter by tag name |
| `topic` | string | Filter by topic name |
| `project_id` | string | Filter by project ID |
| `person_id` | string | Filter by person ID |

### `/graph` Query Parameters

| Parameter | Value | Description |
|-----------|-------|-------------|
| `mode` | `full` | All node types (up to 500 nodes) |
| `mode` | `papers` | Papers, People, Topics only |
| `mode` | `paper` | Single paper neighbourhood (`&id={paper_id}`) |

---

## Cypher, Export, Backfill

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/cypher/schema` | Live Neo4j schema (labels, types, keys) |
| `POST` | `/cypher/run` | Run raw Cypher (max 500 rows) |
| `POST` | `/cypher/assist` | Ollama generates Cypher from natural language |
| `DELETE` | `/cypher/nodes/{id}` | Delete any node by ID |
| `GET` | `/export/bibtex` | Download BibTeX for all papers |
| `POST` | `/backfill/topics` | Bulk AI topic assignment |
| `POST` | `/backfill/summary` | Bulk AI summarisation |
| `POST` | `/backfill/figures` | Bulk figure extraction |

---

## Knowledge Chat

| Method | Path | Description |
|--------|------|-------------|
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
  "model": "claude"
}
```

The response is an SSE stream of events:

| Event type | Content |
|------------|---------|
| `progress` | Step-by-step context assembly log |
| `token` | Single response token |
| `done` | Final message with conversation ID |
| `error` | Error message |

---

## Health

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check — returns `{status, neo4j}` |

---

## Interactive API Docs

With the backend running, visit:

- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`
- **OpenAPI JSON**: `http://localhost:8000/openapi.json`
