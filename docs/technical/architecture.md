# Architecture

This page describes the overall system design of PaperManager, how the modules interact, and the key architectural principles.

---

## High-Level Overview

```mermaid
graph TB
    subgraph "User Interfaces"
        Browser["🌐 Browser\n(React + Vite :5173)"]
        ClaudeDesktop["💬 Claude Desktop\n(MCP Client)"]
    end

    subgraph "Backend — FastAPI :8000"
        Routers["routers/\n(HTTP endpoints)"]
        MCPTools["tools/\n(MCP tool handlers)"]
        Services["services/\n(business logic)"]
        DBQueries["db/queries/\n(Cypher)"]
    end

    subgraph "External Services"
        Neo4j["🗄️ Neo4j Aura\n(Graph DB)"]
        Drive["📁 Google Drive\n(PDF / Figure storage)"]
        S2["🔍 Semantic Scholar\n(Metadata / Citations)"]
        Claude["🤖 Anthropic Claude\n(Summaries / Chat)"]
        Ollama["🦙 Ollama\n(Local LLM)"]
    end

    Browser <-->|"HTTP / SSE"| Routers
    ClaudeDesktop <-->|"MCP stdio"| MCPTools
    MCPTools --> Services
    MCPTools --> DBQueries
    Routers --> Services
    Routers --> DBQueries
    DBQueries <--> Neo4j
    Services --> Drive
    Services --> S2
    Services --> Claude
    Services --> Ollama
```

---

## The Shared Layer Principle

The most important architectural rule in PaperManager:

> **`db/queries/` and `services/` are framework-neutral.** Neither FastAPI nor MCP specifics leak into them. `routers/` and `tools/` are two different entry points over the same logic.

```mermaid
flowchart LR
    HTTP["HTTP Request"] --> R["routers/"]
    MCP["MCP Tool Call"] --> T["tools/"]
    R --> Shared
    T --> Shared

    subgraph Shared["Shared Layer (framework-neutral)"]
        direction TB
        DB["db/queries/ — all Cypher"]
        SVC["services/ — Drive, AI, PDF parsing"]
    end

    DB --> Neo4j["Neo4j Aura"]
    SVC --> External["Google Drive / Claude / Ollama"]
```

This means every capability is available both via HTTP (for the browser) and via MCP tool calls (for Claude Desktop), without any code duplication.

---

## Module Map

```mermaid
graph LR
    subgraph backend["backend/"]
        main["main.py\n(FastAPI app)"]
        config["config.py\n(env vars)"]
        mcp["mcp_server.py\n(MCP entry point)"]

        subgraph routers["routers/"]
            rPapers["papers.py"]
            rPeople["people.py"]
            rTags["tags.py"]
            rTopics["topics.py"]
            rProjects["projects.py"]
            rSearch["search.py"]
            rGraph["graph.py"]
            rChat["knowledge_chat.py"]
            rCypher["cypher.py"]
            rExport["export.py"]
            rBackfill["backfill.py"]
            rFigures["figures.py"]
            rBulk["bulk_import.py"]
        end

        subgraph tools["tools/"]
            tPaper["paper_tools.py"]
            tNote["note_tools.py"]
            tTag["tag_tools.py"]
            tPerson["person_tools.py"]
            tProject["project_tools.py"]
            tAI["ai_tools.py"]
        end

        subgraph services["services/"]
            sAI["ai.py\n(Claude)"]
            sDrive["drive.py\n(Google Drive)"]
            sPDF["pdf_parser.py"]
            sMeta["metadata_lookup.py\n(S2 / CrossRef)"]
            sURL["metadata_from_url.py"]
            sFig["figure_extractor.py"]
            sNote["note_parser.py"]
            sRefs["references.py"]
            sBulk["bulk_resolver.py"]
        end

        subgraph db["db/"]
            conn["connection.py\n(Neo4j driver)"]
            schema["schema.py\n(indexes + constraints)"]
            subgraph queries["queries/"]
                qPapers["papers.py"]
                qPeople["people.py"]
                qTopics["topics.py"]
                qTags["tags.py"]
                qNotes["notes.py"]
                qProjects["projects.py"]
            end
        end

        subgraph models["models/"]
            schemas["schemas.py\n(Pydantic)"]
        end
    end

    main --> routers
    mcp --> tools
    routers --> services
    routers --> db
    tools --> services
    tools --> db
```

---

## Paper Ingestion Flow

The most complex path through the system — from PDF drop to fully enriched paper:

```mermaid
sequenceDiagram
    participant Browser
    participant Router as routers/papers.py
    participant PDFParser as services/pdf_parser.py
    participant MetaLookup as services/metadata_lookup.py
    participant Drive as services/drive.py
    participant AI as services/ai.py
    participant DB as db/queries/papers.py
    participant Neo4j

    Browser->>Router: POST /papers/upload (PDF bytes)
    Router->>PDFParser: extract_text(pdf_bytes)
    PDFParser-->>Router: raw_text
    Router->>PDFParser: find_doi(raw_text)
    alt DOI found
        Router->>MetaLookup: lookup_semantic_scholar(doi)
        alt S2 fails
            Router->>MetaLookup: lookup_crossref(doi)
        end
    else No DOI
        Router->>PDFParser: extract_metadata_with_llm(raw_text[:3000])
        alt Ollama unavailable
            Router->>PDFParser: extract_metadata_heuristic(raw_text)
        end
    end
    Router->>Drive: upload_pdf(pdf_bytes)
    Drive-->>Router: drive_file_id
    Router->>AI: summarize_paper(abstract, raw_text)
    AI-->>Router: summary
    Router->>DB: create_paper(metadata + summary + drive_file_id)
    DB->>Neo4j: MERGE (p:Paper {...})
    Router->>DB: link_authors(paper_id, authors)
    Router->>DB: link_topics(paper_id, topics)
    Router-->>Browser: PaperOut JSON
```

---

## Note Save Flow

```mermaid
sequenceDiagram
    participant Browser
    participant Router as routers/papers.py
    participant NoteParser as services/note_parser.py
    participant DB as db/queries/notes.py
    participant Neo4j

    Browser->>Router: PUT /papers/{id}/note (markdown)
    Router->>NoteParser: parse_mentions(markdown)
    NoteParser-->>Router: {people: [...], topics: [...]}
    Router->>DB: save_note(paper_id, content)
    DB->>Neo4j: MERGE (n:Note {content})\n-[:ABOUT]->(paper)
    Router->>DB: upsert_mentions(note_id, people, topics)
    DB->>Neo4j: MERGE mentions relationships
    Router-->>Browser: Note JSON
```

---

## Key Design Decisions

See the full [Decisions Log](../decisions.md) for rationale. The key principles:

1. **Neo4j over SQL** — papers, people, topics, and tags are naturally a graph; enables path queries, co-authorship derivation, topic clustering
2. **Tags as nodes** — `(Paper)-[:TAGGED]->(Tag)` allows efficient "all papers with tag X" queries
3. **Topic ≠ Tag** — Topics are formal research areas linked to person specialties; Tags are free-form personal labels
4. **Notes as graph nodes** — Notes need their own `@mention` and `#topic` relationships; a text field on Paper would lose graph power
5. **Shared service layer** — MCP tools and HTTP routers call the same `db/` and `services/` code
6. **Prompts as files** — All prompt templates live in `prompts/` and are loaded fresh on each call; edit without restarting the backend
