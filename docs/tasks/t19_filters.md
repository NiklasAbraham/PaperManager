# T19 — Filters (Tag / Topic / Project / Person)

**Phase:** 5 — Frontend
**Depends on:** T07, T08, T17
**Touches:** `frontend/src/pages/Library.tsx` (update), sidebar filter components

## Goal
The Library sidebar filters are wired to real API data.
Selecting a filter narrows the paper grid.

## Filter state
Stored in URL params so filters are shareable/bookmarkable:
```
/?tag=arxiv&topic=NLP&project_id=abc123
```

## Filter panel items

Each section loads from its endpoint:
- Tags → `GET /tags` → shows name + count
- Topics → `GET /topics`
- Projects → `GET /projects`
- People → `GET /people`

Clicking a filter value:
1. Adds it to URL params
2. Triggers `GET /search` with filter params
3. Grid updates

Multiple filters = AND logic (narrow down).
Click again to deselect.

## Active filter chips
Show active filters as removable chips above the paper grid:
```
Showing: [arxiv ×] [NLP ×]   Clear all
```

## Done when
- [ ] Tag list loads with counts
- [ ] Clicking a tag filters papers
- [ ] Active filter shown as chip, clickable to remove
- [ ] Multiple filters work together (AND)
- [ ] URL updates when filters change
- [ ] Navigating back restores filter state from URL

## Tests
- Manual: select tag → grid narrows → chip appears → remove chip → grid resets
