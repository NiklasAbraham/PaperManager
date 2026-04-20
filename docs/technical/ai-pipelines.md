# AI Pipelines

PaperManager uses multiple AI models for different tasks. This page documents each pipeline, the models used, and how they fit together.

---

## Models Used

| Model | Provider | Used for |
|-------|----------|----------|
| `claude-opus-4-6` | Anthropic | Paper summarisation, single-paper chat, knowledge chat |
| `claude-haiku-4-5-20251001` | Anthropic | Abstract extraction, reference extraction, topic suggestion, conversation compaction |
| `llama3.2:3b` | Ollama (local) | Metadata extraction (layer 2), tag suggestion, arXiv query generation, figure captions, affiliation extraction, Cypher assist |
| Claude Vision | Anthropic | Figure chat, figure captioning (claude-vision mode) |

All Anthropic calls can be routed through an enterprise Foundry gateway by setting `ANTHROPIC_WORK_API_KEY` and `ANTHROPIC_WORK_BASE_URL`.

---

## Metadata Extraction Pipeline (PDF Upload)

Runs when a PDF is uploaded. Tries four strategies in order, stopping at the first success:

```mermaid
flowchart TD
    Start["PDF bytes"] --> Extract["Docling extracts raw_text"]
    Extract --> FindDOI{DOI / arXiv ID\nfound in text?}

    FindDOI -->|"Yes"| S2["Layer 1a: Semantic Scholar API"]
    S2 -->|fail| CR["Layer 1a fallback: CrossRef API"]

    FindDOI -->|"No DOI but\ntitle found"| S2Title["Layer 1b: S2 title search"]

    FindDOI -->|"Nothing found"| Ollama["Layer 2: Ollama llama3.2:3b\non first 3 000 chars"]
    Ollama -->|"Ollama unavailable"| Heuristic["Layer 3: Regex heuristics\n(first line = title, year regex)"]

    S2 --> AbstractCheck{Abstract\nextracted?}
    CR --> AbstractCheck
    S2Title --> AbstractCheck
    Ollama --> AbstractCheck
    Heuristic --> AbstractCheck

    AbstractCheck -->|"No"| AbstractFallback["ABSTRACT_RE regex →\nClaude Haiku if regex fails"]
    AbstractCheck -->|"Yes"| Done["✅ Metadata ready"]
    AbstractFallback --> Done
```

### Layer Details

| Layer | Trigger | Service | Output |
|-------|---------|---------|--------|
| 1a (primary) | DOI or arXiv ID in text | `services/metadata_lookup.py` → Semantic Scholar | title, year, authors, abstract, topics, citation count, venue |
| 1a (fallback) | S2 fails | CrossRef API | title, year, authors, doi, venue |
| 1b | Title found, no DOI | S2 title search | same as 1a |
| 2 | No DOI, no useful title | Ollama `llama3.2:3b` on `raw_text[:3000]` | title, year, authors (structured JSON) |
| 3 | Ollama unavailable | Regex on raw_text | title (first non-empty line), year (4-digit year regex) |
| Abstract fallback | Abstract still missing | `ABSTRACT_RE` regex → Claude Haiku | abstract text |

The `metadata_source` property on the Paper node records which layer was used.

---

## Paper Summarisation

Triggered after PDF upload or via `POST /backfill/summary`.

```mermaid
flowchart LR
    A["abstract + raw_text"] --> P["Load prompts/summary.txt"]
    P --> C["Claude Opus 4.6\n(claude-opus-4-6)"]
    C --> S["summary string\nsaved to Paper.summary"]
```

The prompt template at `prompts/summary.txt` structures the output as:
- Problem / motivation
- Key method or contribution
- Main findings
- Relevance

---

## Topic Suggestion

Triggered during upload or via `POST /papers/{id}/topics/suggest` or bulk backfill.

```mermaid
flowchart LR
    A["title + abstract"] --> P["Load prompts/topics.txt"]
    P --> C["Claude Haiku\n(claude-haiku-4-5-20251001)"]
    C --> T["3–6 title-case topic strings\ne.g. 'Protein Structure Prediction'"]
    T --> DB["MERGE Topic nodes\n+ ABOUT relationships"]
```

---

## Tag Suggestion

Triggered in the upload modal (optional step) or via `POST /tags/suggest`.

```mermaid
flowchart LR
    A["title + abstract"] --> O["Ollama llama3.2:3b"]
    O --> Tags["List of tag names\nfrom seeded tag vocabulary"]
```

Ollama is constrained to suggest only tags from the existing tag vocabulary.

---

## Reference Extraction Pipeline

Triggered when the user clicks "Extract References" on the Paper Detail page, or via `GET /papers/{id}/extract-references`.

```mermaid
flowchart TD
    Start["Paper with raw_text"] --> A{DOI available?}
    A -->|"Yes"| S2["Strategy A:\nSemantic Scholar /references API"]
    A -->|"No"| B["Strategy B:\nRegex on REFERENCES section\nof raw_text"]
    S2 -->|"< 3 results"| B
    B -->|"< 3 results"| Claude["Strategy C:\nClaude Haiku on last 30%\nof raw_text"]
    S2 -->|"≥ 3 results"| Done["✅ Reference list"]
    B -->|"≥ 3 results"| Done
    Claude --> Done
```

Each extracted reference creates a `Paper` stub node (title + DOI) tagged `from-references` and linked via `CITES`. Stubs are enriched if the full paper is later imported.

---

## Single-Paper Chat

Triggered via `POST /papers/{id}/chat`.

```mermaid
flowchart LR
    Q["User question"] --> P["Load prompts/chat_system.txt"]
    P --> C["Selected model:\nClaude Opus / Claude Work / Ollama"]
    C --> R["Context: raw_text\n(truncated to model limit)"]
    R --> Response["Streaming response\nreturned to browser"]
```

---

## Figure Extraction & Captioning

Triggered via `POST /papers/{id}/figures/extract`.

```mermaid
flowchart TD
    PDF["PDF from Google Drive"] --> Docling["Docling: extract\npage images + figure regions"]
    Docling --> Method{Caption method\nfrom settings}
    Method -->|"docling"| DocCaption["Docling structural caption"]
    Method -->|"ollama"| OllamaCaption["Ollama llama3.2:3b\nfrom prompts/figure_captions.txt"]
    Method -->|"claude-vision"| ClaudeCaption["Claude Vision\n(claude-haiku)"]
    DocCaption --> Upload["Upload PNG to Google Drive"]
    OllamaCaption --> Upload
    ClaudeCaption --> Upload
    Upload --> DB["Save Figure node in Neo4j"]
```

---

## Figure Vision Chat

Triggered via `POST /papers/{id}/figures/{fig_id}/chat`.

The figure image is retrieved from Google Drive and sent to Claude with the question:

```
System: You are analysing a scientific figure.
User: [image bytes] + question text
```

---

## Knowledge Chat Context Assembly

Triggered via `POST /knowledge-chat/stream`.

```mermaid
flowchart TD
    Q["User question"] --> Parse["Parse @mentions\n@tag:, @topic:, @project:, @paper:"]
    Parse -->|"Mentions found"| Cypher["Run Cypher queries\nto fetch matching papers"]
    Parse -->|"No mentions"| Recent["Fetch 10 most recently\nadded papers"]
    Cypher --> Budget["Apply token budget\nper paper (truncate raw_text)"]
    Recent --> Budget
    Budget --> System["Load prompts/knowledge_chat_system.txt"]
    System --> Claude["Claude Opus 4.6\n(streaming SSE)"]
    Claude --> Browser["Token-by-token response\nto browser"]
```

---

## Affiliation Extraction

Triggered as part of the paper upload when author affiliations are missing.

```mermaid
flowchart LR
    T["raw_text first 2 000 chars"] --> P["Load prompts/author_affiliations.txt"]
    P --> O["Ollama llama3.2:3b"]
    O --> A["author → affiliation mapping"]
    A --> DB["Update Person.affiliation in Neo4j"]
```

---

## Prompt Templates

All prompts live in `prompts/` and are loaded fresh on each call — edit without restarting:

| File | Used in | Purpose |
|------|---------|---------|
| `summary.txt` | `ai.py` | Paper summarisation |
| `topics.txt` | `ai.py` | Topic suggestion |
| `chat_system.txt` | `ai.py` | Single-paper Q&A system prompt |
| `knowledge_chat_system.txt` | `knowledge_chat.py` | Multi-paper synthesis system prompt |
| `figure_captions.txt` | `figure_extractor.py` | Figure caption generation |
| `author_affiliations.txt` | `pdf_parser.py` | Author affiliation extraction |
