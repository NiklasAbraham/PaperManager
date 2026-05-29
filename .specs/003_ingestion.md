# Ingestion Workflows

All ways to get content into PaperManager.

---

## PDF Upload

Drag a PDF onto the Library page or click **+** → **PDF** tab.

### Metadata Extraction Pipeline (4 layers)

```
PDF bytes
  │
  ├─ Docling: extract raw_text
  │
  ├─ Layer 1a: Find DOI or arXiv ID in text
  │     → Semantic Scholar API (title, year, authors, abstract, topics, citation count, venue)
  │     → CrossRef API (fallback if S2 fails)
  │
  ├─ Layer 1b: S2 title search
  │     (if title found but no DOI)
  │
  ├─ Layer 2: Ollama llama3.2:3b on first 3 000 chars
  │     (if no DOI found)
  │
  ├─ Layer 3: Regex heuristics
  │     (first non-empty line = title, year regex)
  │     (if Ollama unavailable)
  │
  └─ Abstract fallback: ABSTRACT_RE regex → Claude Haiku
        (if abstract still missing after above layers)
```

`metadata_source` on the Paper node records which layer succeeded.

### After Metadata Extraction

A **confirmation modal** shows the extracted metadata. You can review and override any field before committing. A duplicate check runs against existing papers (by DOI and title).

### Upload Pipeline (after confirmation)

1. PDF uploaded to Google Drive → `drive_file_id` stored
2. Paper node created in Neo4j (or existing stub enriched if DOI matches)
3. Claude Opus generates AI summary from abstract + full text
4. Claude Haiku extracts `Claim` nodes
5. Ollama `nomic-embed-text` generates embedding (if enabled in Settings)
6. Authors linked as `Person` nodes; affiliation extraction runs if affiliations missing
7. Topics suggested by Claude Haiku (3–6 title-case), linked via `ABOUT`
8. References extracted and shown for review (S2 API → regex → Claude Haiku)
9. Figures extracted from PDF pages (Docling / Ollama / Claude Vision per settings)
10. Paper auto-tagged `pdf-upload`

### Upload Modal Options

| Option | Default | Description |
|---|---|---|
| Source step | on | Record how you found the paper (person, LinkedIn, Twitter, conference, etc.) |
| Summary prompt step | on | Edit AI summary instructions before upload |
| Auto-save references | off | Skip reference review, save all automatically |
| Tags step | on | Review AI-suggested tags before saving |

---

## URL / DOI Ingest

Click **+** → **URL / DOI** tab. Paste any of:

| Input | Example |
|---|---|
| arXiv URL | `https://arxiv.org/abs/1706.03762` |
| arXiv ID | `1706.03762` or `arXiv:1706.03762` |
| DOI URL | `https://doi.org/10.1038/nature14539` |
| Bare DOI | `10.1038/nature14539` |
| PubMed URL | `https://pubmed.ncbi.nlm.nih.gov/12345678/` |
| bioRxiv URL | `https://www.biorxiv.org/content/10.1101/...` |
| medRxiv URL | `https://www.medrxiv.org/content/10.1101/...` |

Metadata fetched from source APIs (arXiv Atom, Semantic Scholar, CrossRef, PubMed eUtils, bioRxiv). No PDF stored. Paper auto-tagged `from-url`.

Endpoint: `POST /papers/from-url` (metadata only) or `POST /papers/from-url-full` (+ PDF download attempt).

---

## Bulk Import

Go to **Bulk Import** in the nav bar. Upload or paste JSON:

```json
{
  "fetch_pdf": true,
  "project_id": "optional-project-uuid",
  "papers": [
    {"url": "https://arxiv.org/abs/1706.03762"},
    {"arxiv": "1810.04805"},
    {"doi": "10.1038/nature14539"},
    {"url": "https://pubmed.ncbi.nlm.nih.gov/30082513/"},
    {"title": "AlphaFold protein structure prediction"},
    {"title": "CRISPR-Cas9 genome editing", "fetch_pdf": false}
  ]
}
```

Each entry needs at least one of: `url`, `arxiv`, `doi`, `title`. Formats can be mixed.

**Resolution order per entry:**
1. `url` → existing URL resolver (arXiv, DOI, PubMed, bioRxiv)
2. `arxiv` → arXiv API
3. `doi` → Semantic Scholar → CrossRef
4. `title` → S2 title search → arXiv title search → Ollama-improved arXiv search

**PDF fetching** (`fetch_pdf: true`):
- arXiv: downloaded from `arxiv.org/pdf/{id}`
- Other: Unpaywall API checked for open-access PDF URL

Progress is a live SSE log stream. Papers that already exist by DOI are reported as "skipped". All imported papers auto-tagged `bulk-import`.

Endpoint: `POST /papers/bulk-import` (SSE stream)

---

## Literature Search

Go to **Literature** page. Set keywords, run search across arXiv / PubMed / bioRxiv. Results streamed via SSE. Papers already in your library are marked. Click to add any result.

Can be scoped to a project by selecting one before running.

Endpoint: `POST /literature/search` (SSE stream)

---

## Discover

Go to **Discover** page. Search external sources and add individual results to your library in one click.

Endpoint: `POST /discover/search`

---

## Blog Posts

Go to **Blogs** page. Register an RSS feed URL → the backend fetches and parses posts. Full content is fetched on first view of a post. AI summary generated on import.

Endpoint: `POST /blogs`, `POST /blogs/{id}/fetch-posts`

---

## Reference Import

From a paper's detail view → **References** tab → **Extract References**. The system runs the three-strategy pipeline and shows results for review. Click **Save** to create stub `Paper` nodes linked via `CITES`. If a stub's DOI matches a later full import, the stub is enriched.

**Three-strategy pipeline:**
1. Semantic Scholar `/references` API (requires DOI) — preferred
2. Regex on the `REFERENCES` section of `raw_text`
3. Claude Haiku on the last 30% of `raw_text` (when strategies 1+2 give < 3 results)

All reference stubs are auto-tagged `from-references`.

---

## Author Tracking

On a Person's detail page, toggle **Track author**. The backend periodically queries Semantic Scholar for new papers by that author (using `s2_author_id`) and auto-imports them.

Endpoint: `POST /people/{id}/track`
