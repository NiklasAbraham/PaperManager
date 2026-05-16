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
    │   └── client.ts        # All fetch calls to the backend (typed)
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
    │   └── UserPicker.tsx       # Active user selector (navbar)
    │
    └── pages/
        ├── Library.tsx          # Main view: paper grid + filters + dashboard
        ├── PaperDetail.tsx      # Single paper: metadata, PDF, figures, notes, chat
        ├── People.tsx           # People list + person detail
        ├── Projects.tsx         # Project list + project detail
        ├── Graph.tsx            # Knowledge graph (WebGL force-graph)
        ├── KnowledgeChat.tsx    # Multi-paper AI chat
        ├── Cypher.tsx           # Cypher editor
        ├── Settings.tsx         # App settings
        ├── BulkImport.tsx       # Bulk paper import
        ├── LiteratureSearch.tsx # Stream recent papers from arXiv / PubMed / bioRxiv
        ├── Discover.tsx         # Search external sources + add to library
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
| `/graph` | `Graph` | Knowledge graph visualisation |
| `/knowledge` | `KnowledgeChat` | Multi-paper AI chat |
| `/cypher` | `Cypher` | Cypher query editor |
| `/bulk-import` | `BulkImport` | Bulk paper import |
| `/literature` | `LiteratureSearch` | Recent paper stream from external sources |
| `/discover` | `Discover` | Search external sources + add to library |
| `/blogs` | `Blogs` | Blog list |
| `/blogs/posts/:postId` | `BlogPostDetail` | Single blog post |
| `/teammates` | `Teammates` | Collaborator view (no navbar link) |
| `/merge` | `MergeManager` | Duplicate detection and merge |
| `/settings` | `Settings` | Application settings |

---

## Key Pages

### Library (`Library.tsx`)

Main landing page. Shows a paper grid with search, filters (tag, topic, project, person), view mode toggle, and a drag-and-drop upload zone. Includes a stats dashboard.

### PaperDetail (`PaperDetail.tsx`)

Single paper view with:

- Metadata panel (left): title, authors, year, tags, topics, people, rating
- Tab panel (center): PDF viewer, Figures, Notes (NoteEditor), References, Chapters, Claims, Annotations
- Chat panel (right): single-paper Q&A (ChatPanel)

### Graph (`Graph.tsx`)

Uses **force-graph** (WebGL) to render the knowledge graph. Fetches from `GET /graph?mode=...`. Clicking a node opens `EntityPanel` for details.

### KnowledgeChat (`KnowledgeChat.tsx`)

Multi-paper AI chat. Sends messages to `POST /knowledge-chat/stream` (SSE). Supports `@tag:`, `@topic:`, `@project:`, `@paper:` mention syntax to scope context.

### LiteratureSearch (`LiteratureSearch.tsx`)

Streams recent papers from arXiv, PubMed, and bioRxiv using keyword lists. Papers can be added to the library in one click.

### Discover (`Discover.tsx`)

Unified external search across arXiv, Semantic Scholar, and PubMed. Shows which results are already in the library; adds missing ones via URL ingest.

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
