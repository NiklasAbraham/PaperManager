# Architecture Decision Log

## 2026-04-16 — Initial design session

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

### Metadata extraction: three-layer chain
1. DOI regex → Semantic Scholar API (preferred) or Crossref (fallback) — covers ~80-90% of papers
2. Ollama + llama3.2:3b local LLM — for papers without DOI (drafts, internal reports)
3. Regex heuristics — last resort, user corrects in UI
`metadata_source` field on Paper node records which layer was used.
Semantic Scholar also returns topics + citation count → auto-populates Topic nodes.

### MCP server shares the same service layer as FastAPI
`db/queries/` and `services/` are framework-neutral.
FastAPI `routers/` and MCP `tools/` are just two thin entry-point layers over the same logic.
This means every capability is available both via HTTP and via Claude Code tool calls.
PDF upload is intentionally not exposed as an MCP tool — file upload via browser only.

### No Collection node (for now)
Projects serve a similar purpose and are already in scope.
Can revisit if the need for lightweight grouping (reading lists) emerges.

### Backend: FastAPI on Railway
Simple deploy, free tier, Python-native.

### Frontend: React, local first
Start with local dev, deploy to Vercel when ready.
