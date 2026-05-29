# Architecture Decision Log

## 2026-04-16 — Initial Design Session

### DB: Neo4j Aura (cloud) over SQLite
Papers, people, topics, and tags are naturally a graph.
Enables path queries, co-authorship derivation, topic clustering.
Free tier (200k nodes / 400k relationships) sufficient for personal use.

### Tags as nodes, not property arrays
Tags are first-class citizens for filtering and browsing.
`(Paper)-[:TAGGED]->(Tag)` lets you query "all papers with this tag" efficiently.

### Topic ≠ Tag
- `Topic` = formal research area, linked to Person specialties
- `Tag` = free-form personal label (source, status, context, anything)

### Notes as separate nodes
Notes need their own `@mention` and `#topic` relationships.
A text field on Paper would lose this graph power.

### INVOLVES relationship with role property
Instead of many typed relationships for workflow states,
one `INVOLVES {role}` relationship keeps the schema flexible.
New roles can be invented freely without schema changes.

### Metadata extraction: four-layer chain
1. DOI regex → Semantic Scholar API (preferred) or CrossRef (fallback) — covers ~80–90% of papers
2. Ollama + llama3.2:3b local LLM — for papers without DOI (drafts, internal reports)
3. Regex heuristics — last resort, user corrects in UI
4. Abstract fallback: ABSTRACT_RE regex → Claude Haiku

`metadata_source` field on Paper node records which layer was used.
Semantic Scholar also returns topics + citation count → auto-populates Topic nodes.

### MCP server shares the same service layer as FastAPI
`db/queries/` and `services/` are framework-neutral.
FastAPI `routers/` and MCP `tools/` are two thin entry-point layers over the same logic.
Every capability is available both via HTTP and via Claude Desktop tool calls.
PDF upload is intentionally not exposed as an MCP tool — file upload via browser only.

### No Collection node (for now)
Projects serve a similar purpose and are already in scope.
Can revisit if the need for lightweight grouping (reading lists) emerges.

### Backend: FastAPI
Python-native, strong async support, automatic OpenAPI docs.

### Frontend: React + Vite + Tailwind
Standard modern SPA stack; fast HMR during development.

---

## 2026-04-20 — Knowledge Features

### Knowledge Chat: agentic tool-use over hybrid retrieval
Instead of stuffing all paper text into context, the backend pre-loads a relevance-ranked
subset and gives Claude two tools: `run_cypher` (live graph queries) and `semantic_search`
(vector similarity). Claude decides what additional data it needs.
This keeps context manageable while allowing Claude to chase any lead in the graph.

### Vector embeddings on Paper nodes
768-dim Ollama `nomic-embed-text` embeddings stored directly on `Paper.embedding`.
A Neo4j vector index (`paper_embeddings`) enables ANN cosine search at query time.
Chosen over a separate vector store (Pinecone, etc.) to keep the stack minimal.

### Hybrid retrieval: vector + recency fallback
Vector search alone fails when embeddings haven't been generated yet (cold start).
The recency fallback (10 most recently added papers) ensures Knowledge Chat is useful
from day one without a backfill step.

### Conversation compaction with structured working memory
Simple truncation loses context. Claude Haiku extracts a JSON block of key findings,
open questions, and decisions before compaction. Specific numbers and paper titles
survive in the structured JSON even after the messages are replaced.

---

## 2026-04-25 — Enrichment & Discovery

### Claims as graph nodes
Claim extraction enables evidence-level queries via Cypher.
Claims are NOT injected into Knowledge Chat context by default (would bloat it);
Claude pulls them on demand via `run_cypher` when it needs evidence-level detail.

### Chapters for books and lecture decks
`document_type` on Paper controls the upload pipeline.
Books and lecture decks skip summary/figures/references/claims but support chapters.
Chapters are detected in three passes: Docling structural → regex → Ollama AI.

### Blogs as first-class nodes
Technical blog posts (Distill, Lil'Log, etc.) are valuable context alongside papers.
`Blog` (feed) and `BlogPost` (individual post) nodes allow the same tag/project/chat
workflows used for papers to apply to blog content.

### Annotations (PDF highlights) stored in Neo4j
Highlights stored as `Annotation` nodes linked to Paper, not as PDF metadata.
This keeps annotations queryable and database-portable.

### Author tracking with Semantic Scholar
`Person.tracked = true` + `Person.s2_author_id` enables automatic import of new papers.
S2 is queried periodically; new papers are ingested just like URL ingest.

---

## 2026-05-01 — Security & Deployment

### JWT authentication with admin-managed users
Single-user primary focus, but multi-user support needed for collaboration.
JWT stored in localStorage; admin user manages create/update/delete.
Admin capabilities restricted to username `niklas` in current implementation.

### Rate limiting as in-process middleware
Sliding-window rate limiter in `services/rate_limit.py` (no Redis dependency).
Stricter limits on `/auth/login` to prevent brute-force attacks.

### Docker Compose + Traefik for production
Three services: Neo4j, FastAPI backend, Nginx-served React frontend.
Traefik handles SSL (Let's Encrypt) and routing.
Neo4j and backend are internal-only; only the Nginx container is internet-facing.
