# T17 — Library Page + Drag & Drop Upload

**Phase:** 5 — Frontend
**Depends on:** T13 (ingest endpoint), T16
**Touches:** `frontend/src/pages/Library.tsx`, `frontend/src/components/PaperDrop.tsx`, `frontend/src/components/PaperCard.tsx`

## Goal
The main page. Shows all papers as cards. Has a drag & drop zone to upload a new PDF.

## Components

### PaperDrop.tsx
- Uses `react-dropzone`
- Accepts `.pdf` files only
- On drop: POST multipart to `/papers`
- Shows upload progress (spinner)
- On success: adds new card to the grid without page reload

### PaperCard.tsx
Props: `paper: Paper`
Shows:
- Title
- Year + Venue (if available)
- First 2 lines of summary
- Tag badges (coloured pills)
- Topic badges
- Project label (if in any project)
- Click → navigate to `/paper/:id`

### Library.tsx
- Calls `GET /papers` on mount, renders PaperCard grid
- Sidebar filters: by tag, topic, project, person
- Search bar at top → calls `GET /search?q=...`
- PaperDrop zone at top or as a floating button

## Layout sketch

```
┌─────────────────────────────────────────────────────┐
│  [Search bar.........................]  [+ Drop PDF] │
├──────────────┬──────────────────────────────────────┤
│ FILTERS      │  [Card] [Card] [Card]                 │
│              │  [Card] [Card] [Card]                 │
│ Tags         │  [Card] [Card]                        │
│ > arxiv (4)  │                                       │
│ > to-read(2) │                                       │
│              │                                       │
│ Topics       │                                       │
│ > NLP (6)    │                                       │
│              │                                       │
│ Projects     │                                       │
│ > PhD (8)    │                                       │
└──────────────┴──────────────────────────────────────┘
```

## Done when
- [ ] Papers load from backend on page open
- [ ] Drag & drop a PDF → new card appears after upload
- [ ] Clicking a card navigates to PaperDetail
- [ ] Filter by tag → grid updates
- [ ] Search → grid updates

## Tests
- Manual UI test: drop a PDF, verify card appears with title + summary
