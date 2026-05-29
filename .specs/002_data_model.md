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
| `document_type` | string | `"paper"` / `"book"` / `"lecture_deck"` |
| `venue` | string | Journal or conference name |
| `embedding` | float[] | 768-dim Ollama vector (nomic-embed-text) |
| `created_at` | datetime | |
| `updated_at` | datetime | |

`metadata_source` values: `semantic_scholar`, `crossref`, `arxiv`, `pubmed`, `biorxiv`, `medrxiv`, `llm`, `heuristic`, `bulk`

`document_type` behaviour:
- `paper` — gets summary, figures, references, claims (default)
- `book` — skips summary/figures/refs/claims; supports chapters
- `lecture_deck` — same as book

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
| `ABOUT` | Note → Paper |
| `MENTIONS` | Note → Person (`@PersonName`) |
| `MENTIONS` | Note → Topic (`#TopicName`) |

### Projects
| Rel | Direction |
|---|---|
| `CONTAINS` | Project → Paper |
| `CONTAINS` | Project → BlogPost |
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
| `paper_search` | Fulltext | Paper(title, abstract, summary) | `/search` |
| `note_search` | Fulltext | Note(content) | Note search |
| `message_search` | Fulltext | Message(content) | Conversation search |
| `claim_search` | Fulltext | Claim(text) | `/claims/search` |
| `paper_embeddings` | Vector (cosine, 768-dim) | Paper(embedding) | Semantic similarity (nomic-embed-text) |

---

## Seeded Tags (157 total)

Categories seeded on startup:

- **Source:** `pdf-upload`, `from-url`, `from-references`, `bulk-import`, `from-linkedin`, `from-twitter`, `from-email`, `from-conference`, `from-newsletter`, `from-google-scholar`, `from-colleague`
- **Workflow:** `to-read`, `reading`, `read`, `important`, `revisit`, `needs-review`, `relevant`, `in-bibliography`, `reproduced`, `code-available`
- **Content type:** `review`, `benchmark`, `dataset`, `method`, `theory`, `negative-result`, `foundational`, `highly-cited`, `sota`
- **Math:** algebra, topology, differential geometry, probability, statistics, optimization, graph theory, information theory, and more
- **ML/AI:** machine-learning, deep-learning, transformers, LLMs, diffusion models, GNNs, Bayesian inference, and ~40 more
- **Physics/Simulation:** statistical mechanics, quantum mechanics, molecular dynamics, Monte Carlo, biophysics, and more
- **Biology:** protein structure/folding/design, genomics, CRISPR, single-cell, evolutionary biology, and more
- **Drug discovery:** drug design, molecular docking, ADMET, QSAR, retrosynthesis, PROTAC, and more
