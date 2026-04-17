# Data Model — Neo4j Graph Schema

## Nodes

### Paper
| Property | Type | Description |
|---|---|---|
| `id` | string (uuid) | Internal ID |
| `title` | string | Paper title |
| `year` | integer | Publication year |
| `doi` | string | DOI if available |
| `abstract` | string | Original abstract |
| `summary` | string | AI-generated summary (Claude) |
| `drive_file_id` | string | Google Drive file ID for the PDF |
| `created_at` | datetime | When added to the system |

### Person
| Property | Type | Description |
|---|---|---|
| `id` | string (uuid) | Internal ID |
| `name` | string | Full name |
| `affiliation` | string | Institution / company |
| `email` | string | Optional |

### Topic
| Property | Type | Description |
|---|---|---|
| `id` | string (uuid) | Internal ID |
| `name` | string | Topic name (e.g. "machine learning") |
| `description` | string | Optional longer description |

### Tag
| Property | Type | Description |
|---|---|---|
| `id` | string (uuid) | Internal ID |
| `name` | string | Free-form label (e.g. "linkedin", "to-read", "from_karin") |

### Venue
| Property | Type | Description |
|---|---|---|
| `id` | string (uuid) | Internal ID |
| `name` | string | Journal or conference name |
| `type` | string | "journal" / "conference" / "preprint" |

### Note
| Property | Type | Description |
|---|---|---|
| `id` | string (uuid) | Internal ID |
| `content` | string | Markdown content |
| `created_at` | datetime | Creation time |
| `updated_at` | datetime | Last edit time |

### Project
| Property | Type | Description |
|---|---|---|
| `id` | string (uuid) | Internal ID |
| `name` | string | Project name |
| `description` | string | What this project is about |
| `status` | string | "active" / "paused" / "done" |

---

## Relationships

### Bibliographic
```
(Paper)-[:AUTHORED_BY]->(Person)
(Paper)-[:PUBLISHED_IN]->(Venue)
(Paper)-[:CITES]->(Paper)
```

### Classification
```
(Paper)-[:ABOUT]->(Topic)
(Paper)-[:TAGGED]->(Tag)
```

### Workflow
```
(Paper)-[:IN_PROJECT]->(Project)
(Paper)-[:HAS_NOTE]->(Note)
(Paper)-[:INVOLVES {role: string}]->(Person)
```

#### INVOLVES roles (open list — add freely)
| Role | Meaning |
|---|---|
| `"feedback_needed"` | You need feedback from this person |
| `"working_on"` | This person is working on this topic/paper |
| `"shared_by"` | This person shared the paper with you |
| `"collaborating"` | You are collaborating with this person on this |

### People & expertise
```
(Person)-[:SPECIALIZES_IN]->(Topic)
(Project)-[:RELATED_TO]->(Project)
```

### Note parsing (auto-created from Markdown)
```
(Note)-[:MENTIONS]->(Person)    ← from @Name syntax
(Note)-[:MENTIONS]->(Topic)     ← from #Topic syntax
```

---

## Example graph fragment

```
(Paper "Attention Is All You Need")
  -[:AUTHORED_BY]-> (Person "Vaswani")
  -[:PUBLISHED_IN]-> (Venue "NeurIPS")
  -[:ABOUT]-> (Topic "transformers")
  -[:ABOUT]-> (Topic "natural language processing")
  -[:TAGGED]-> (Tag "arxiv")
  -[:TAGGED]-> (Tag "foundational")
  -[:IN_PROJECT]-> (Project "PhD thesis")
  -[:INVOLVES {role: "feedback_needed"}]-> (Person "Nele")
  -[:INVOLVES {role: "shared_by"}]-> (Person "Karin")
  -[:HAS_NOTE]-> (Note "Key insight: attention mechanism replaces RNNs...")
  -[:CITES]-> (Paper "Neural Machine Translation by...")

(Person "Jan")
  -[:SPECIALIZES_IN]-> (Topic "transformers")

(Project "PhD thesis")-[:RELATED_TO]->(Project "Collaboration TU Berlin")
```

---

## Open questions / future extensions
- Should Notes also be taggable directly (not just via #Topic mentions)?
- Add an `Institution` node and link `Person -[:AFFILIATED_WITH]-> Institution`?
- AI-suggested `RELATED_TO` links between Topics?
- Embedding vectors on Paper nodes for semantic search?
