# Library

The Library is the main page of PaperManager (`/`). It shows all papers in your collection and provides powerful search and filtering tools.

---

## Landing page

With no query and no filters the page shows, top to bottom:

- A header line, **Library · 1,163 papers**.
- A small **dashboard** with the **topic map** (see the next section).
- **Continue reading**: one slim row of up to three papers whose reading status is *Reading*,
  most recently touched first (two on a phone). It is hidden when you are not reading anything.
- **Recently added**: your papers as cards, newest first, a page at a time (20, 50, 100 or
  200 per page, see Settings). The sort menu on the right of the heading changes the order.

The papers are loaded one page at a time from the server, so the page opens quickly however
large the library is.

The bar at the top stays in view while you scroll: the search box, a **Filters** button with a
badge showing how many filters are active, the **+** button to add papers and a **⋯** menu with
*Surprise me*, *Find research gaps* and *Manage tags / topics / authors / projects*.

---

## Dashboard and topic map

Above the paper list, the unfiltered Library page shows four small tiles and, below them, a map of your library. The map
card can be folded away; the page remembers that.

**The strip**

- **Added**: papers added this week and this month, with a small bar chart of the last twelve weeks.
- **Reading**: how many papers are unread, being read and read. Click a bar to filter the list by that status.
- **Topics**: your biggest topics. Click a chip to filter by that topic.
- **Projects**: your projects with their paper counts. Click one to filter by it. Hover a project to see where its papers sit on the map.

**The map**

- Each dot is a paper, placed by meaning: papers about similar things sit close together.
- Big dots are your library. Small, faint dots are cited references; use the **references** toggle to show or hide them.
- Colours are clusters of related papers, each with a label. A grey "Unparsed references" cluster collects reference entries that could not be read properly.
- Hover a dot to see the title, click it to open the paper.
- Zoom with **Ctrl** (or **⌘**) and the mouse wheel, or pinch on a trackpad. Drag with the mouse to pan. **Reset zoom** brings the whole map back.

The dashboard only appears on the plain Library page; as soon as you search or set a filter, it gives way to the results.
After an update the first build of the map takes up to a minute or two ("Laying out your library..."); later updates keep
the dots where they were.

Prefer a different layout? Add `?dash=a` (stats column beside a larger map) or `?dash=c` (cards floating over the map) to the
address, or `?dash=off` to hide the dashboard and keep only the heading.

---

## Search

Type in the search box at the top. Results appear as you type (250 ms after the last
keystroke, or at once on **Enter**), ranked by relevance, and every row says **why** it matched:
chips such as *Title*, *Author: Tero Karras*, *Topic: Diffusion Models*, *Your note*,
*Highlight*, *Full text* or *Meaning 0.78*, and one or two passages with the matched words
marked.

### What is searched

| Where | Weight |
|---|---|
| DOI or arXiv id typed as the query | exact match, always first |
| Title | highest; extra when every word or the whole query is in the title |
| Authors | high; a query that is someone's name puts their papers first |
| Your notes and your PDF highlights (with their comments) | high |
| Topics, tags | medium |
| Abstract, AI summary, extracted claims | medium |
| Venue | low |
| Extracted full text of the PDF | lowest (every word must occur in it) |

A paper has to contain **every word** of the query somewhere in those fields (one word in the
author list and another in the title is fine). If no paper does, the papers that contain some
of the words are shown with a note saying so. Papers cited by many other papers in your
library rank a little higher among equally good matches.

Case and accents never matter: `edm`, `EDM` and `Edm` find the same papers, as do `Kynkaanniemi`
and `Kynkäänniemi`, in the search, the suggestions and the filters.

### Syntax

| You type | It finds |
|---|---|
| `diffusion` | diffusion, diffusions, Diffusion-based (every word is also a prefix) |
| `diffus*` | any word starting with *diffus* |
| `scroe based` | score-based: words of 5+ letters tolerate one typo |
| `"flow matching"` | the exact phrase only |
| `alphafold3` | AlphaFold3 and AlphaFold 3 |
| `over-conditioning`, `co-folding` | the two parts next to each other (over-conditioning, over conditioning) and the joined word (cofolding) |
| `10.1038/s41586-024-07487-w`, `https://doi.org/…`, `2210.02747`, `arXiv:2210.02747` | that paper |
| `the`, `of`, `for` … | ignored unless the query has nothing else |

Other punctuation (`:`, brackets, slashes) is treated as a word break, so `title: diffusion` or
`SE(3)` are safe to type.

### Suggestions

From the second character on, a dropdown lists matching **papers** (by title), **authors**,
**topics**, **tags** and **projects** with their paper counts. Use ↑ / ↓ and **Enter**, or click:
a paper opens it; an author, topic, tag or project becomes a filter (and the typed text is
cleared). **Esc** closes the list.

### Modes, sort, references

Above the results:

- **Exact** matches words only. **Hybrid** (the default) also ranks papers whose title and
  abstract *mean* something close to the query, which helps for questions in plain language
  ("why do co-folding models collapse to one pose"). **Meaning** ranks by meaning alone. Meaning
  search needs a one-time embedding of the library in the background (a few minutes); until it
  is ready, the page says so and shows exact matches.
- **Sort**: Relevance (default with a query) or any of the sorts listed under
  [Sort](#sort) below. The default sort in Settings applies to browsing without a query.
- **References**: also search the cited references that have no PDF in your library (hidden by
  default; they rank below your own papers).

The query, filters, mode, sort and the references switch are kept in the URL, so a search can
be bookmarked or shared. When nothing matches, the page offers to search the references, to
search by meaning, or to remove the filters.

The **✦** button next to the box still turns a plain-language request into filters with the
AI model.

## Filters {#filters}

A shorter walk-through with the speed notes is on [Search and filters](search-filters.md).

Click **Filters** next to the search box. A panel opens (a sheet from the bottom on a phone)
and every change applies at once, so the list updates behind it while you click. Filters work
with or without a search query and can be combined.

| Filter | How it works |
|--------|-------------|
| **Added** | Any time, Today, Last 7 days, Last 30 days, Last 90 days, or a **Custom range** with two dates. "Today" starts at midnight, your local time; the end date of a custom range is included. |
| **Year** | From and to year of publication (either may stay empty). |
| **Reading status** | Unread (includes papers you never gave a status), Reading, Read. |
| **Rating at least** | 1 to 5 stars or more. |
| **Document type** | Paper, Book, Lecture deck, News article. |
| **Project** | Papers in the chosen project. |
| **Properties** | Has PDF, Has full text, Has note, Has highlights, Bookmarked: each *Any / Yes / No*. |
| **Tag**, **Topic**, **Venue** | Start typing and pick from your own names (case does not matter). |
| **Author** | Not in the panel: pick an author in the search suggestions. |
| **Sort by** | Same list as the sort menu above the results. |

Active filters appear as removable chips under the search bar, with **Clear all**. Picking a
tag, topic, author or project from the search suggestions adds the same filter. Without a
query the filtered papers are shown as cards with their count ("37 papers"); with a query they
are the search result rows.

### Sharing a filtered view

Everything is in the address bar: `q`, `mode`, `sort`, `refs`, `tag`, `topic`, `project_id`,
`person_id`, `venue`, `reading_status`, `bookmarked`, `year_min`, `year_max`, `rating_min`,
`document_type`, `has_pdf`, `has_text`, `has_note`, `has_highlights` (`1` or `0`), and `added`
(`today`, `7d`, `30d`, `90d`) or `added_from` / `added_to` (`YYYY-MM-DD`). Copy the URL to
bookmark the view or send it to someone with access to the same library. Presets such as
`added=7d` are relative to the moment the page is opened, so "last 7 days" stays the last 7
days.

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

### Sort {#sort}

Offered in the filter panel and in the menu above the results. *Relevance* appears only with
a search query.

| Sort option | Description |
|-------------|-------------|
| Relevance | Best match first (queries only) |
| Newest added | Newest first (default when browsing) |
| Oldest added | Oldest first |
| Recently updated | Last changed first |
| Year, new to old / old to new | By publication year |
| Title A to Z | Alphabetical |
| Rating | Highest rated first |
| Citations | Most cited first |

### Page size

Choose how many papers to show per page in Settings: **20**, **50**, **100**, or **All**
(shown in pages of 200). Changing page scrolls back to the top.

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
- Click the **+** button → choose PDF upload or URL/DOI ingest. If the Library is filtered by a
  project, new papers are added to that project automatically and the project step of the
  upload wizard is skipped.
- Open **Tools → Bulk import** in the top bar for batch import
- Open **Explore → Find papers** to search arXiv, Semantic Scholar, PubMed and bioRxiv (tab **Search**) or to browse recent papers for your keywords (tab **Feed**), and add papers with one click

---

## Settings Reference

Library display settings are persisted to `localStorage`:

| Setting | Options | Default |
|---------|---------|---------|
| Default sort | date desc/asc, year desc/asc, title asc, rating, citations | date desc |
| Abstract preview | on / off | on |
| Papers per page | 20 / 50 / 100 / all | 50 |

See [Settings](../user-guide/getting-started.md) for all available options.
