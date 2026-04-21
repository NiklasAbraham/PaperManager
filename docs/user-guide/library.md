# Library

The Library is the main page of PaperManager (`/`). It shows all papers in your collection and provides powerful search and filtering tools.

---

## Dashboard

When no filters are active you see a dashboard at the top showing:

- **Count cards** — total papers, authors, topics, tags, projects
- **Papers by year** bar chart
- **Top topics** list
- **Recently added** papers

---

## Search

The search bar at the top performs full-text search across:

- Paper title
- Abstract
- AI-generated summary

Results update as you type. The search query is reflected in the URL so you can bookmark filtered views.

---

## Filters {#filters}

The left sidebar provides filters that narrow down the paper list:

| Filter | How it works |
|--------|-------------|
| **Tag** | Shows papers tagged with the selected tag |
| **Topic** | Shows papers about the selected research topic |
| **Project** | Shows papers belonging to the selected project |
| **Person** | Shows papers authored by or involving the selected person |

Multiple filters can be combined. Active filters appear as removable chips below the search bar.

### Tag Categories

157 tags are seeded on startup:

=== "Source"
    `pdf-upload`, `from-url`, `from-references`, `bulk-import`, `from-linkedin`, `from-twitter`, `from-email`, `from-conference`, `from-newsletter`, `from-google-scholar`, `from-colleague`

=== "Workflow"
    `to-read`, `reading`, `read`, `important`, `revisit`, `needs-review`, `relevant`, `in-bibliography`, `reproduced`, `code-available`

=== "Content type"
    `review`, `benchmark`, `dataset`, `method`, `theory`, `negative-result`, `foundational`, `highly-cited`, `sota`

=== "Math"
    `algebra`, `topology`, `differential-geometry`, `probability`, `statistics`, `optimization`, `graph-theory`, `information-theory`, and more

=== "ML / AI"
    `machine-learning`, `deep-learning`, `transformers`, `LLMs`, `diffusion-models`, `GNNs`, `bayesian-inference`, and ~40 more

=== "Physics / Simulation"
    `statistical-mechanics`, `quantum-mechanics`, `molecular-dynamics`, `monte-carlo`, `biophysics`, and more

=== "Biology"
    `protein-structure`, `protein-folding`, `protein-design`, `genomics`, `CRISPR`, `single-cell`, `evolutionary-biology`, and more

=== "Drug discovery"
    `drug-design`, `molecular-docking`, `ADMET`, `QSAR`, `retrosynthesis`, `PROTAC`, and more

---

## View Options

### View mode

Toggle between **grid** and **list** view using the buttons in the top-right corner.

- **Grid** — compact cards ideal for large libraries
- **List** — more detail per row, easier to scan metadata

### Sort

| Sort option | Description |
|-------------|-------------|
| Date added ↓ | Newest first (default) |
| Date added ↑ | Oldest first |
| Year ↓ | Latest publication year first |
| Title A→Z | Alphabetical |

### Page size

Choose how many papers to show per page: **20**, **50**, **100**, or **All**.

---

## Paper Cards

Each paper card shows:

- **Title** and **year**
- **Authors** (up to 3, then "et al.")
- **Metadata source badge** (colour-coded: green / yellow / red)
- **Abstract preview** (toggleable in Settings)
- **Tags** as coloured pills
- **Quick edit** and **delete** buttons

Click any card to open the [Paper Detail](paper-detail.md) view.

---

## Adding Papers

From the Library page:

- **Drag and drop** a PDF file onto the page → upload flow starts
- Click the **+** button → choose PDF upload or URL/DOI ingest
- Navigate to **Bulk Import** in the nav bar for batch import

---

## Settings Reference

Library display settings are persisted to `localStorage`:

| Setting | Options | Default |
|---------|---------|---------|
| Default view | grid / list | grid |
| Default sort | date desc/asc, year desc, title asc | date desc |
| Abstract preview | on / off | on |
| Papers per page | 20 / 50 / 100 / all | 20 |

See [Settings](../user-guide/getting-started.md) for all available options.
