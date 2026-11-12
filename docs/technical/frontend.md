# Frontend

The frontend is a **React 19 + TypeScript** single-page application built with **Vite** and styled with **Tailwind CSS**.

---

## Directory Layout

```text
frontend/
├── index.html
├── package.json
├── vite.config.ts
├── tsconfig.json
│
└── src/
    ├── main.tsx             # React entry point (ReactDOM.createRoot)
    ├── App.tsx              # Router setup + NavBar
    ├── App.css
    ├── index.css
    │
    ├── api/
    │   ├── client.ts        # All fetch calls to the backend (typed)
    │   └── insights.ts      # Tokens, Reports, Suggestions and Health calls
    │
    ├── types/
    │   └── index.ts         # TypeScript types matching backend Pydantic schemas
    │
    ├── contexts/
    │   ├── SettingsContext.tsx  # App settings persisted to localStorage
    │   └── UserContext.tsx      # Active user identity
    │
    ├── components/
    │   ├── PaperDrop.tsx        # Drag-and-drop PDF upload zone
    │   ├── PaperCard.tsx        # Paper summary card (grid / list view)
    │   ├── NoteEditor.tsx       # Markdown editor with @/# autocomplete
    │   ├── ChatPanel.tsx        # Chat sidebar (single paper)
    │   ├── EditPaperModal.tsx   # Edit paper metadata modal
    │   ├── UploadConfirmModal.tsx  # Multi-step upload confirmation modal
    │   ├── OnboardingModal.tsx  # Post-upload onboarding (refs, tags, project, people)
    │   ├── EntityPanel.tsx      # Knowledge graph node properties panel
    │   ├── PdfAnnotator.tsx     # In-browser PDF highlight + annotation UI
    │   ├── BookChapters.tsx     # Chapter list + chapter chat panel
    │   ├── ResearchGapPanel.tsx # Research gap analysis results panel
    │   ├── nav/             # NavBar, NavMenu, MobileDrawer; navConfig.ts is the single source of the navigation
    │   ├── search/          # SearchBox, FilterMenu (popover / bottom sheet), filterState (URL <-> filters), LibraryMenu
    │   ├── graph/           # Cypher query panel, result table, examples, saved queries
    │   ├── kchat/           # Knowledge chat: ToolCall rows, TurnSources, FigureStrip, structure cards, copyTex, composer
    │   ├── insights/        # Shared pieces of Tokens / Reports / Suggestions / Health (BarChart, DataTable, StatRow, SuggestionChip)
    │   ├── literature/      # ExternalSearch and KeywordFeed (the two tabs of Find papers)
    │   └── UserPicker.tsx       # Active user selector (navbar)
    │
    └── pages/
        ├── Library.tsx          # Main view: paper grid + filters + dashboard
        ├── PaperDetail.tsx      # Single paper: metadata, PDF, figures, notes, chat
        ├── People.tsx           # People list + person detail
        ├── Projects.tsx         # Project list + project detail
        ├── Graph.tsx            # Knowledge graph (WebGL force-graph) + Cypher query panel (components/graph/)
        ├── KnowledgeChat.tsx    # Multi-paper AI chat
        ├── Cypher.tsx           # Redirects to /graph?view=query
        ├── Tokens.tsx           # Usage ledger: totals, charts, breakdowns, calls
        ├── Reports.tsx          # Report list + new report form
        ├── ReportView.tsx       # One report: progress, text, cited papers, export
        ├── Suggestions.tsx      # Improvement ideas, votes, status
        ├── Health.tsx           # Admin system health
        ├── Settings.tsx         # App settings
        ├── BulkImport.tsx       # Bulk paper import
        ├── LiteratureSearch.tsx # Stream recent papers from arXiv / PubMed / bioRxiv
        ├── Discover.tsx         # Legacy; /discover redirects to /literature?tab=search
        ├── Blogs.tsx            # Blog list + blog post reader
        ├── BlogPostDetail.tsx   # Single blog post view
        ├── Venues.tsx           # Venue browser
        ├── MergeManager.tsx     # Duplicate detection + merge UI
        └── Teammates.tsx        # Teammate / collaborator view
```

---

## Routing

React Router v7 defines the page routes in `App.tsx`:

| Route | Page component | Description |
| ----- | -------------- | ----------- |
| `/` | `Library` | Paper grid, search, filters, dashboard |
| `/paper/:id` | `PaperDetail` | Single paper detail |
| `/people` | `People` | People list and detail |
| `/projects` | `Projects` | Project list and detail |
| `/venues` | `Venues` | Venue browser |
| `/conferences` | `Conferences` | Conference explorer: every conference-year |
| `/conferences/:key` | `Conferences` | One conference: overview, institutions (`?view=institutions&inst=`), topics (`?view=topics&q=`) |
| `/graph` | `Graph` | Knowledge graph visualisation; `?view=query` opens the admin Cypher query panel, `?q=` preloads it |
| `/knowledge` | `KnowledgeChat` | Multi-paper AI chat |
| `/cypher` | `Cypher` | Redirect to `/graph?view=query` (keeps `?q=`) |
| `/bulk-import` | `BulkImport` | Bulk paper import |
| `/literature` | `LiteratureSearch` | Find papers: tab Search (arXiv, Semantic Scholar, PubMed, bioRxiv) and tab Feed (keyword stream) |
| `/discover` | redirect | Goes to `/literature?tab=search` (Discover is part of Find papers) |
| `/chat` | redirect | Goes to `/knowledge` |
| `/reports`, `/reports/:id` | `Reports`, `ReportView` | Report list and one report |
| `/tokens` | `Tokens` | Usage ledger |
| `/suggestions` | `Suggestions` | Improvement ideas |
| `/health` | `Health` | System health (admin) |
| `/tools`, `/tools/ideogram`, `/admin` | `Tools`, `IdeogramChat`, `AdminConsole` | Tools hub, image generation, admin console |
| `/blogs` | `Blogs` | Blog list |
| `/blogs/posts/:postId` | `BlogPostDetail` | Single blog post |
| `/teammates` | `Teammates` | Collaborator view (no navbar link) |
| `/merge` | `MergeManager` | Duplicate detection and merge |
| `/settings` | `Settings` | Application settings |

---

## Key Pages

### Library (`Library.tsx`)

Main landing page. One sticky bar holds the search box, the **Filters** popover (`components/search/FilterMenu.tsx`; a bottom sheet on phones), the add button and the **⋯** menu. All query and filter state lives in the URL (`filterState.ts`, pure and unit-tested). Without a query it shows *Continue reading* and *Recently added*, loaded one page at a time; with a query, ranked rows with matched-in chips.

### PaperDetail (`PaperDetail.tsx`)

Single paper view with:

- Metadata panel (left): title, authors, year, tags, topics, people, rating
- Tab panel (center): PDF viewer, Figures, Notes (NoteEditor), References, Chapters, Claims, Annotations
- Chat panel (right): single-paper Q&A (ChatPanel)

### Graph (`Graph.tsx`)

Uses **force-graph** (WebGL) to render the knowledge graph. Fetches from `GET /graph?mode=...`. Clicking a node opens `EntityPanel` for details. For admins, **Query** opens `components/graph/CypherPanel.tsx`: one `POST /graph/query` run feeds a Graph tab (drawn in the main canvas) and a Table tab (`ResultTable`); examples, saved queries (localStorage), schema and AI assist live there too.

### KnowledgeChat (`KnowledgeChat.tsx`)

Multi-paper AI chat, laid out like the desk chat. Sends messages to `POST /knowledge-chat/stream` (SSE) and renders each event as it arrives: `step` events become `ToolCall` rows, `interim` text the model's notes between them, `token` the answer, `suggestion` a `SuggestionChip`. Under an answer: `TurnSources` (papers it cited, read or searched), `FigureStrip` with a lightbox, concept cards, structure cards (`kchat/structure/`, 3Dmol.js; PDB, AlphaFold DB, ligands by CCD or PubChem) and KaTeX maths with copy-as-TeX (`copyTex.ts`). **Stop** calls `POST /knowledge-chat/stop`; retry re-asks. Supports `@tag:`, `@topic:`, `@project:`, `@paper:`, `@person:`, `@user:` mentions to scope context.

### LiteratureSearch (`LiteratureSearch.tsx`)

Streams recent papers from arXiv, PubMed, and bioRxiv using keyword lists. Papers can be added to the library in one click.

### Find papers (Discover folded in)

`LiteratureSearch.tsx` has two tabs: **Search** (`components/literature/ExternalSearch.tsx`: arXiv, Semantic Scholar, PubMed and bioRxiv, showing which results are already in the library) and **Feed** (`KeywordFeed.tsx`). The old Discover page is gone.

### Tokens, Reports, Suggestions, Health

Four pages over the same small kit (`components/insights/`, API in `api/insights.ts`). `Tokens.tsx` reads `/tokens/summary`, `/tokens/calls` and `/tokens/prices`; `Reports.tsx` and `ReportView.tsx` poll `/reports` while a report runs and offer Markdown and HTML export; `Suggestions.tsx` lists, votes and (admins) sets status; `Health.tsx` reads `/system/health` (admin only, refresh button). They are lazy-loaded.

### Navigation (`components/nav/`)

`navConfig.ts` is the single source for the desktop bar, the dropdowns and the mobile drawer: four primary entries (Library, Projects, People, Chat) and the Explore, Tools and Account menus; entries can be admin-only. `redirects.tsx` keeps old routes (`/cypher`, `/chat`) working.

### Conferences (`Conferences.tsx`)

Conference explorer. The landing page lists every conference-year by field with its build
state (polling while one builds); a conference page has three views kept in the URL:
overview, a ranked institution table with an institution card (`InstitutionsView`,
`InstitutionCard`), and topic search (`TopicView`). `AreaBar` draws an area mix, optionally
against the conference's; `PaperRow` expands to the abstract and closest papers and adds a
paper to the library. Components live in `components/conferences/`.

### Blogs (`Blogs.tsx`) and BlogPostDetail (`BlogPostDetail.tsx`)

Register RSS feeds or blog URLs. Posts are fetched, indexed, and browsable alongside papers. Each post supports notes, tags, people links, and project membership.

### MergeManager (`MergeManager.tsx`)

Scans the library for near-duplicate papers using Ollama or Claude. Presents candidate pairs with similarity scores; user confirms which to merge.

---

## Key Components

### UploadConfirmModal + OnboardingModal

Two-stage upload flow:

1. **UploadConfirmModal** — metadata review, document type selection, upload confirmation
2. **OnboardingModal** — post-upload: references review, tag selection, project assignment, people linking

### NoteEditor (`NoteEditor.tsx`)

Markdown editor with `@`/`#` autocomplete for people and topics. Toggle between edit and preview modes.

### ChatPanel (`ChatPanel.tsx`)

Single-paper chat sidebar with model selector (Claude Opus, Claude Work, Ollama) and streaming response rendering.

### PdfAnnotator (`PdfAnnotator.tsx`)

In-browser PDF viewer with highlight and annotation support. Annotations are saved as graph nodes linked to the Paper.

### BookChapters (`BookChapters.tsx`)

Chapter list for books/lecture decks. Each chapter can be summarised or chatted with independently.

### UserPicker (`UserPicker.tsx`)

Navbar dropdown for selecting the active user. User identity is stored in `UserContext` and sent with knowledge chat requests.

---

## State Management

The app uses **React's built-in state** (`useState`, `useEffect`, `useContext`) with no external state library.

- `SettingsContext` — app settings persisted to `localStorage`
- `UserContext` — active user identity, used for conversation attribution

---

## Dependencies

| Package | Purpose |
| ------- | ------- |
| `react` 19 | UI framework |
| `react-router-dom` 7 | Client-side routing |
| `tailwindcss` 4 | Utility-first CSS |
| `force-graph` | WebGL graph visualisation |
| `react-markdown` | Markdown rendering |
| `react-dropzone` | Drag-and-drop PDF upload |

---

## Development

```bash
cd frontend
npm install
npm run dev      # Starts Vite dev server on :5173

npm run build    # Production build → dist/
npm run lint     # ESLint check
```

The Vite config proxies `/api` requests to `http://localhost:8000` during development.
