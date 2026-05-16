# Data Model

PaperManager uses **Neo4j Aura** (a cloud-hosted graph database) to store all entities and their relationships.

---

## Node Labels

### Paper

The central entity. Every ingested paper, book, or lecture deck is a `Paper` node.

| Property | Type | Description |
| -------- | ---- | ----------- |
| `id` | string (UUID) | Internal identifier |
| `title` | string | Paper title |
| `year` | integer | Publication year |
| `doi` | string | DOI if available |
| `abstract` | string | Original abstract |
| `summary` | string | AI-generated summary (Claude Opus) |
| `raw_text` | string | Full extracted PDF text (stripped from API responses) |
| `drive_file_id` | string | Google Drive file ID for the PDF |
| `citation_count` | integer | From Semantic Scholar |
| `metadata_source` | string | How metadata was obtained (see below) |
| `reading_status` | string | `"unread"` / `"reading"` / `"read"` |
| `rating` | integer | 1–5 star rating |
| `bookmarked` | boolean | Bookmarked flag |
| `color` | string | Colour label (hex or name) |
| `document_type` | string | `"paper"` / `"book"` / `"lecture_deck"` |
| `venue` | string | Journal or conference name |
| `embedding` | float[] | Ollama embedding vector (768-dim, nomic-embed-text) |
| `created_at` | datetime | When added to the system |
| `updated_at` | datetime | Last modification time |

### Person

Authors, collaborators, colleagues.

| Property | Type | Description |
| -------- | ---- | ----------- |
| `id` | string (UUID) | Internal identifier |
| `name` | string | Full name |
| `affiliation` | string | Institution or company |
| `email` | string | Optional contact |
| `bio` | string | Short biography |
| `phone` | string | Optional phone |
| `orcid_url` | string | ORCID profile URL |
| `scholar_url` | string | Google Scholar URL |
| `linkedin_url` | string | LinkedIn URL |
| `website_url` | string | Personal website |
| `skills` | string | JSON-encoded list of skills |
| `startup_roles` | string | JSON-encoded list of `{name, role, active}` |
| `tracked` | boolean | Whether new papers by this author are auto-imported |
| `s2_author_id` | string | Semantic Scholar author ID |
| `citation_count` | integer | Total citations from S2 |
| `last_enriched_at` | datetime | When person data was last enriched |

### Topic

Formal research areas.

| Property | Type | Description |
| -------- | ---- | ----------- |
| `id` | string (UUID) | Internal identifier |
| `name` | string | Topic name, title-case (e.g. `"Protein Structure Prediction"`) |
| `description` | string | Optional longer description |

### Tag

Free-form personal labels.

| Property | Type | Description |
| -------- | ---- | ----------- |
| `id` | string (UUID) | Internal identifier |
| `name` | string | Label (e.g. `"to-read"`, `"from-karin"`) |

### Project

Named collection of papers and blog posts.

| Property | Type | Description |
| -------- | ---- | ----------- |
| `id` | string (UUID) | Internal identifier |
| `name` | string | Project name |
| `description` | string | What this project is about |
| `status` | string | `"active"` / `"paused"` / `"done"` |
| `created_at` | datetime | Creation time |

### Note

Markdown note attached to a paper.

| Property | Type | Description |
| -------- | ---- | ----------- |
| `id` | string (UUID) | Internal identifier |
| `content` | string | Markdown text |
| `created_at` | datetime | Creation time |
| `updated_at` | datetime | Last edit time |

### Figure

Extracted figure from a PDF.

| Property | Type | Description |
| -------- | ---- | ----------- |
| `id` | string (UUID) | Internal identifier |
| `paper_id` | string | ID of parent paper |
| `figure_number` | integer | Sequential figure number |
| `caption` | string | Auto-generated caption |
| `drive_file_id` | string | Google Drive file ID for the PNG image |
| `drive_url` | string | Direct download URL |
| `page_number` | integer | PDF page the figure was on |
| `created_at` | datetime | When extracted |

### Annotation

PDF highlight / annotation created in-browser.

| Property | Type | Description |
| -------- | ---- | ----------- |
| `id` | string (UUID) | Internal identifier |
| `page_number` | integer | Page number in PDF |
| `highlighted_text` | string | Selected text |
| `color` | string | `"yellow"` / `"green"` / `"blue"` / `"red"` / `"purple"` |
| `note` | string | User note on the highlight |
| `position_json` | string | JSON bounding box (opaque to backend) |
| `created_at` | datetime | Creation time |
| `updated_at` | datetime | Last edit time |

### Chapter

A section of a book or lecture deck.

| Property | Type | Description |
| -------- | ---- | ----------- |
| `id` | string (UUID) | Internal identifier |
| `paper_id` | string | ID of parent Paper |
| `number` | integer | Chapter sequence number |
| `title` | string | Chapter title |
| `level` | integer | 1 = chapter, 2 = sub-chapter |
| `summary` | string | AI-generated chapter summary |
| `start_page` | integer | First PDF page (1-indexed) |
| `end_page` | integer | Last PDF page (1-indexed) |
| `created_at` | datetime | When created |
| `updated_at` | datetime | Last modified |

### Claim

A factual claim extracted from a paper's text.

| Property | Type | Description |
| -------- | ---- | ----------- |
| `id` | string (UUID) | Internal identifier |
| `text` | string | Claim text |
| `type` | string | Claim category (e.g. `"finding"`, `"method"`, `"limitation"`) |

### Blog

A registered blog / RSS feed.

| Property | Type | Description |
| -------- | ---- | ----------- |
| `id` | string (UUID) | Internal identifier |
| `name` | string | Blog name |
| `url` | string | Blog home URL |
| `feed_url` | string | RSS / Atom feed URL |
| `parser` | string | Feed parser identifier |
| `description` | string | Blog description |
| `created_at` | datetime | When registered |

### BlogPost

An individual post fetched from a Blog's feed.

| Property | Type | Description |
| -------- | ---- | ----------- |
| `id` | string (UUID) | Internal identifier |
| `blog_id` | string | Parent Blog ID |
| `title` | string | Post title |
| `url` | string | Post URL |
| `author` | string | Author name |
| `published_at` | string | Publication date |
| `description` | string | Short excerpt / meta description |
| `content` | string | Full post content (imported on first view) |
| `summary` | string | AI-generated summary |
| `reading_status` | string | `"unread"` / `"reading"` / `"read"` |
| `imported` | boolean | Whether full content has been fetched |
| `created_at` | datetime | When added |
| `updated_at` | datetime | Last modified |

### Conversation

A multi-paper chat conversation.

| Property | Type | Description |
| -------- | ---- | ----------- |
| `id` | string (UUID) | Internal identifier |
| `title` | string | Auto-generated conversation title |
| `compacted` | boolean | Whether history has been compacted |
| `created_at` | datetime | When started |
| `updated_at` | datetime | Last message time |

### Message

A single message in a Conversation.

| Property | Type | Description |
| -------- | ---- | ----------- |
| `id` | string (UUID) | Internal identifier |
| `role` | string | `"user"` or `"assistant"` |
| `content` | string | Message text |
| `tokens_used` | integer | Token count for this message |
| `created_at` | datetime | When sent |

### User

A named user for identity and conversation attribution.

| Property | Type | Description |
| -------- | ---- | ----------- |
| `id` | string (UUID) | Internal identifier |
| `name` | string | Unique display name |

### Table

A table extracted from a paper PDF.

| Property | Type | Description |
| -------- | ---- | ----------- |
| `id` | string (UUID) | Internal identifier |
| `paper_id` | string | Parent Paper ID |
| `table_number` | integer | Sequential table number |
| `caption` | string | Table caption |
| `markdown_content` | string | Table rendered as Markdown |
| `page_number` | integer | PDF page |
| `created_at` | datetime | When extracted |

---

## Relationships

### Bibliographic

| Relationship | Direction | Description |
| ------------ | --------- | ----------- |
| `AUTHORED_BY` | Paper → Person | Author of the paper |
| `CITES` | Paper → Paper | Citation; target may be a stub node |

### Classification

| Relationship | Direction | Description |
| ------------ | --------- | ----------- |
| `ABOUT` | Paper → Topic | Paper covers this research area |
| `TAGGED` | Paper → Tag | Free-form label applied to paper |

### Workflow

| Relationship | Direction | Properties | Description |
| ------------ | --------- | ---------- | ----------- |
| `INVOLVES` | Paper → Person | `role: string` | Non-author workflow relationship |

#### INVOLVES roles

| Role | Meaning |
| ---- | ------- |
| `shared_by` | This person shared the paper with you |
| `working_on` | This person is working on this topic/paper |
| `collaborating` | You are collaborating with this person |
| `feedback_needed` | You need feedback from this person |
| `supervisor` | Supervisor for this work |

### Content

| Relationship | Direction | Description |
| ------------ | --------- | ----------- |
| `HAS_ANNOTATION` | Paper → Annotation | PDF highlight/annotation |
| `HAS_CHAPTER` | Paper → Chapter | Chapter of a book/deck |
| `HAS_FIGURE` | Paper → Figure | Extracted figure |
| `HAS_TABLE` | Paper → Table | Extracted table |
| `HAS_CLAIM` | Paper → Claim | Extracted factual claim |

### Projects

| Relationship | Direction | Description |
| ------------ | --------- | ----------- |
| `CONTAINS` | Project → Paper | Paper belongs to project |
| `CONTAINS` | Project → BlogPost | Blog post belongs to project |
| `RELATED_TO` | Project ↔ Project | Bidirectional project link |

### Notes

| Relationship | Direction | Description |
| ------------ | --------- | ----------- |
| `ABOUT` | Note → Paper | Note belongs to paper |
| `MENTIONS` | Note → Person | `@PersonName` in note text |
| `MENTIONS` | Note → Topic | `#TopicName` in note text |

### Blogs

| Relationship | Direction | Description |
| ------------ | --------- | ----------- |
| `HAS_POST` | Blog → BlogPost | Post belongs to blog |
| `TAGGED` | BlogPost → Tag | Tag on a blog post |
| `INVOLVES` | BlogPost → Person | Person linked to a post |

### People

| Relationship | Direction | Description |
| ------------ | --------- | ----------- |
| `SPECIALIZES` | Person → Topic | Research specialty |
| `RELATED_TO` | Topic ↔ Topic | Bidirectional topic link |

### Conversations

| Relationship | Direction | Description |
| ------------ | --------- | ----------- |
| `HAS_MESSAGE` | Conversation → Message | Message in conversation |
| `BELONGS_TO` | Conversation → User | Conversation owned by user |

---

## Constraints (uniqueness)

| Label | Property | Type |
| ----- | -------- | ---- |
| Paper | id | UNIQUE |
| Person | id | UNIQUE |
| Topic | id | UNIQUE |
| Topic | name | UNIQUE |
| Tag | id | UNIQUE |
| Tag | name | UNIQUE |
| Note | id | UNIQUE |
| Project | id | UNIQUE |
| Figure | id | UNIQUE |
| Annotation | id | UNIQUE |
| Blog | id | UNIQUE |
| BlogPost | id | UNIQUE |
| Conversation | id | UNIQUE |
| Message | id | UNIQUE |
| User | id | UNIQUE |
| User | name | UNIQUE |
| Claim | id | UNIQUE |
| Table | id | UNIQUE |
| Venue | id | UNIQUE |

---

## Indexes

| Index name | Type | Nodes | Properties | Used by |
| ---------- | ---- | ----- | ---------- | ------- |
| `paper_search` | Fulltext | Paper | `title`, `abstract`, `summary` | `/search` endpoint |
| `note_search` | Fulltext | Note | `content` | Note search |
| `message_search` | Fulltext | Message | `content` | Conversation search |
| `claim_search` | Fulltext | Claim | `text` | `/claims/search` |
| `paper_embeddings` | Vector (cosine) | Paper | `embedding` | Semantic similarity (768-dim, nomic-embed-text) |

---

## `metadata_source` Values

Records which metadata extraction layer was used for each paper:

| Value | Description |
| ----- | ----------- |
| `semantic_scholar` | Fetched from Semantic Scholar API |
| `crossref` | Fetched from CrossRef API |
| `arxiv` | Fetched from arXiv Atom API |
| `pubmed` | Fetched from PubMed eUtils |
| `biorxiv` / `medrxiv` | Fetched from bioRxiv/medRxiv API |
| `llm` | Extracted by Ollama LLM from PDF text |
| `heuristic` | Guessed from first lines of PDF |
| `bulk` | Added via bulk import |

---

## `document_type` Values

| Value | Description |
| ----- | ----------- |
| `paper` | Research paper (default) — gets summary, figures, references, claims |
| `book` | Book — skips summary/figures/refs/claims; supports chapters |
| `lecture_deck` | Lecture slides — skips summary/figures/refs/claims; supports chapters |
