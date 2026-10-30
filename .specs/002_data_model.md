# Data Model

PaperManager uses **Neo4j Aura** (cloud graph database). All entities are nodes; all connections are typed relationships.

---

## Nodes

### Paper
The central entity. Every paper, book, or lecture deck is a `Paper` node.

| Property | Type | Notes |
|---|---|---|
| `id` | UUID string | Internal identifier |
| `title` | string | |
| `year` | integer | Publication year |
| `doi` | string | DOI if available |
| `abstract` | string | |
| `summary` | string | AI-generated (Claude Opus) |
| `raw_text` | string | Full extracted PDF text (stripped from API responses) |
| `drive_file_id` | string | Google Drive file ID for the PDF |
| `citation_count` | integer | From Semantic Scholar |
| `metadata_source` | string | Which extraction layer was used (see below) |
| `reading_status` | string | `"unread"` / `"reading"` / `"read"` |
| `rating` | integer | 1–5 star rating |
| `bookmarked` | boolean | |
| `color` | string | Colour label (hex or name) |
| `document_type` | string | `"paper"` / `"book"` / `"lecture_deck"` / `"news_article"` |
| `published_date` | string | ISO date `YYYY-MM-DD`; day-level precision for news articles (papers only store `year`) |
| `venue` | string | Journal or conference name — for a news article, the outlet (e.g. "The New York Times") |
| `embedding` | float[] | 768-dim Ollama vector (nomic-embed-text) |
| `created_at` | datetime | |
| `updated_at` | datetime | |

`metadata_source` values: `semantic_scholar`, `crossref`, `arxiv`, `pubmed`, `biorxiv`, `medrxiv`, `llm`, `heuristic`, `bulk`

`document_type` behaviour:
- `paper` — gets summary, figures, references, claims (default)
- `book` — skips summary/figures/refs/claims; supports chapters
- `lecture_deck` — same as book
- `news_article` — gets summary + claims + embedding + topics, but skips academic references and figures (they don't apply to news). Use `venue` for the outlet and `published_date` for the full date. Scanned newspaper PDFs are OCR'd by Docling like any upload; auto-tagged `from-newspaper`.

### Person
Authors, collaborators, colleagues.

| Property | Type | Notes |
|---|---|---|
| `id` | UUID | |
| `name` | string | Full name |
| `affiliation` | string | Institution/company |
| `email`, `bio`, `phone` | string | Optional contact |
| `orcid_url`, `scholar_url`, `linkedin_url`, `website_url` | string | Profile links |
| `skills` | string | JSON-encoded list |
| `startup_roles` | string | JSON-encoded `[{name, role, active}]` |
| `tracked` | boolean | Whether new papers by this author are auto-imported |
| `s2_author_id` | string | Semantic Scholar author ID |
| `citation_count` | integer | Total citations from S2 |
| `last_enriched_at` | datetime | When person data was last enriched |
| `openalex_id`, `h_index` | string, integer | OpenAlex author ID and h-index (set by the CV builder) |
| `cv`, `cv_status`, `cv_updated_at` | string, string, datetime | JSON-encoded CV (`services/person_cv.py`); status `ok` / `partial` / `mismatch` / `not-found` / `no-papers` |
| `photo`, `photo_source` | string | 256 px JPEG data URI and where it came from |
| `aliases` | list of strings | Names of people merged into this one (`services/person_duplicates.py`) |

### Topic
Formal research areas (e.g. `"Protein Structure Prediction"`).

| Property | Type |
|---|---|
| `id` | UUID |
| `name` | string (unique, title-case) |
| `description` | string (optional) |

### Tag
Free-form personal labels (e.g. `"to-read"`, `"from-karin"`).

| Property | Type |
|---|---|
| `id` | UUID |
| `name` | string (unique) |

### Project
Named collection of papers and blog posts.

| Property | Type |
|---|---|
| `id` | UUID |
| `name` | string |
| `description` | string |
| `status` | `"active"` / `"paused"` / `"done"` |
| `created_at` | datetime |

### Note
Markdown note attached to a paper.

| Property | Type |
|---|---|
| `id` | UUID |
| `content` | string (Markdown) |
| `created_at`, `updated_at` | datetime |

### Figure
Extracted figure from a PDF.

| Property | Type |
|---|---|
| `id` | UUID |
| `paper_id` | string |
| `figure_number` | integer |
| `caption` | string |
| `drive_file_id` | string |
| `drive_url` | string |
| `page_number` | integer |
| `created_at` | datetime |

### Annotation
PDF highlight created in-browser.

| Property | Type |
|---|---|
| `id` | UUID |
| `page_number` | integer |
| `highlighted_text` | string |
| `color` | `"yellow"` / `"green"` / `"blue"` / `"red"` / `"purple"` |
| `note` | string |
| `position_json` | string (opaque bounding box) |
| `created_at`, `updated_at` | datetime |

### Chapter
A section of a book or lecture deck.

| Property | Type |
|---|---|
| `id` | UUID |
| `paper_id` | string |
| `number` | integer (sequence) |
| `title` | string |
| `level` | integer (1 = chapter, 2 = sub-chapter) |
| `summary` | string (AI-generated) |
| `start_page`, `end_page` | integer |
| `created_at`, `updated_at` | datetime |

### Claim
A factual claim extracted from a paper's text by Claude Haiku.

| Property | Type |
|---|---|
| `id` | UUID |
| `text` | string |
| `type` | `"finding"` / `"method"` / `"limitation"` / `"contribution"` |

### Concept
An idea on one PDF page that gets an interactive visualisation (Concepts tab in the paper view). `(Paper)-[:HAS_CONCEPT]->(Concept)`; deleted with the paper.

| Property | Type |
|---|---|
| `id` | UUID |
| `page`, `position` | int (0-based page; order within the scan) |
| `label`, `context` | string (context is what the visualiser model sees) |
| `type` | `"formula"` / `"graph"` / `"2d-text"` / `"2d-anim"` |
| `anchor`, `anchor_found` | verbatim page text used to mark the concept on the PDF; whether it was found in pypdf's text |
| `spec_json` | JSON string of the generated visualisation, absent until first opened |
| `spec_error` | last generation error, if any |
| `created_at`, `updated_at` | datetime |

### MapConcept
A key concept in a project's concept map (Projects → Concept map), shared by every paper that discusses it. Extracted per paper by Gemma (`services/concept_map.py`). Not to be confused with `Concept` (one visualised idea on one PDF page).

| Property | Type |
|---|---|
| `id` | UUID |
| `key` | unique matching key: lower case, alphanumerics only, trailing plural dropped |
| `name`, `kind` | display name; `method` / `model` / `task` / `dataset` / `metric` / `theory` / `phenomenon` / `tool` / `domain` |
| `definition` | one general sentence (first paper's wins) |
| `aliases`, `alias_keys` | single-token abbreviations (FEP, CFG) and their keys; a new concept whose key matches one joins this node |

`(Paper)-[:DISCUSSES {role, in_paper}]->(MapConcept)`; role is `introduces` / `extends` / `uses` / `evaluates` / `critiques` / `background`.
`(MapConcept)-[:CONCEPT_LINK {type, paper_id, evidence}]->(MapConcept)`, one per stating paper; type is `is_a` / `part_of` / `uses` / `extends` / `improves_on` / `alternative_to` / `evaluated_on` / `causes` / `addresses` / `related_to`.
Paper gets `concept_map_at` (or `concept_map_error`). A MapConcept with no DISCUSSES left is deleted on the next save.

### Blog / BlogPost

**Blog** — a registered RSS feed:
`id`, `name`, `url`, `feed_url`, `parser`, `description`, `created_at`

**BlogPost** — an individual post:
`id`, `blog_id`, `title`, `url`, `author`, `published_at`, `description`, `content`, `summary`, `reading_status`, `imported`, `created_at`, `updated_at`

### Conversation / Message

**Conversation** — a multi-paper chat session:
`id`, `title`, `compacted`, `created_at`, `updated_at`

**Message** — a single turn:
`id`, `role` (`"user"` / `"assistant"`), `content`, `tokens_used`, `created_at`

### User
Named user for auth and conversation attribution.
`id`, `name` (unique)

### Table
Extracted table from a PDF.
`id`, `paper_id`, `table_number`, `caption`, `markdown_content`, `page_number`, `created_at`

---

## Relationships

### Bibliographic
| Rel | Direction | Notes |
|---|---|---|
| `AUTHORED_BY` | Paper → Person | Paper author |
| `CITES` | Paper → Paper | Citation; target may be a stub node |

### Classification
| Rel | Direction |
|---|---|
| `ABOUT` | Paper → Topic |
| `TAGGED` | Paper → Tag |

### Workflow
| Rel | Direction | Role values |
|---|---|---|
| `INVOLVES` | Paper → Person | `shared_by`, `working_on`, `collaborating`, `feedback_needed`, `supervisor` |

### Content
| Rel | Direction |
|---|---|
| `HAS_ANNOTATION` | Paper → Annotation |
| `HAS_CHAPTER` | Paper → Chapter |
| `HAS_FIGURE` | Paper → Figure |
| `HAS_TABLE` | Paper → Table |
| `HAS_CLAIM` | Paper → Claim |

### Notes
| Rel | Direction |
|---|---|
| `HAS_NOTE` | Paper → Note (at most one per paper) |
| `WROTE` | User → Note |
| `MENTIONS` | Note → Person (`@PersonName`) |
| `MENTIONS` | Note → Topic (`#TopicName`) |

### Projects
| Rel | Direction |
|---|---|
| `IN_PROJECT` | Paper → Project |
| `MEMBER_OF` | User → Project |
| `RELATED_TO` | Project ↔ Project (bidirectional) |

### Blogs
| Rel | Direction |
|---|---|
| `HAS_POST` | Blog → BlogPost |
| `TAGGED` | BlogPost → Tag |
| `INVOLVES` | BlogPost → Person |

### People & Topics
| Rel | Direction |
|---|---|
| `SPECIALIZES` | Person → Topic |
| `RELATED_TO` | Topic ↔ Topic (bidirectional) |

### Conversations
| Rel | Direction |
|---|---|
| `HAS_MESSAGE` | Conversation → Message |
| `BELONGS_TO` | Conversation → User |

---

## Constraints (Uniqueness)

Paper.id, Person.id, Topic.id, Topic.name, Tag.id, Tag.name, Note.id, Project.id, Figure.id, Annotation.id, Blog.id, BlogPost.id, Conversation.id, Message.id, User.id, User.name, Claim.id, Table.id, Venue.id

---

## Indexes

| Name | Type | Nodes / Properties | Used by |
|---|---|---|---|
| `paper_search` | Fulltext, standard-folding | Paper(title, abstract, summary) | `/search`, suggest |
| `note_search` | Fulltext, standard-folding | Note(content) | `/search` |
| `annotation_search` | Fulltext, standard-folding | Annotation(highlighted_text, note) | `/search` |
| `claim_search` | Fulltext, standard-folding | Claim(text) | `/search`, `/claims/search` |
| `entity_name_search` | Fulltext, standard-folding | Person/Topic/Tag/Project(name) | `/search`, suggest |
| `paper_text_search` | Fulltext, standard-folding, eventually consistent | Paper(venue, raw_text) | `/search` |
| `message_search` | Fulltext | Message(content) | Conversation search |
| `paper_embeddings` | Vector (cosine, 768-dim) | Paper(embedding) | Semantic similarity (nomic-embed-text) |

The library search's own embeddings (bge-small, 384-dim) are a file on disk, not a Neo4j
index: `/data/library_search/emb.npy` + `meta.json`, see `.specs/012_search.md`.

---

## Seeded Tags (157 total)

Categories seeded on startup:

- **Source:** `pdf-upload`, `from-url`, `from-references`, `bulk-import`, `from-linkedin`, `from-twitter`, `from-email`, `from-conference`, `from-newsletter`, `from-google-scholar`, `from-colleague`, `from-newspaper`
- **Workflow:** `to-read`, `reading`, `read`, `important`, `revisit`, `needs-review`, `relevant`, `in-bibliography`, `reproduced`, `code-available`
- **Content type:** `review`, `benchmark`, `dataset`, `method`, `theory`, `negative-result`, `foundational`, `highly-cited`, `sota`
- **Math:** algebra, topology, differential geometry, probability, statistics, optimization, graph theory, information theory, and more
- **ML/AI:** machine-learning, deep-learning, transformers, LLMs, diffusion models, GNNs, Bayesian inference, and ~40 more
- **Physics/Simulation:** statistical mechanics, quantum mechanics, molecular dynamics, Monte Carlo, biophysics, and more
- **Biology:** protein structure/folding/design, genomics, CRISPR, single-cell, evolutionary biology, and more
- **Drug discovery:** drug design, molecular docking, ADMET, QSAR, retrosynthesis, PROTAC, and more
