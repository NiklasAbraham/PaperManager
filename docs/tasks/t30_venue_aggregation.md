# T30 — Venue / Conference Aggregation

**Phase:** 7 — Discovery & Intelligence
**Depends on:** T05
**Touches:** new `backend/routers/venues.py`, `frontend/src/pages/Venues.tsx`, `frontend/src/App.tsx`

## Goal
A "Venues" page that groups your library by conference or journal (e.g. NeurIPS, ICML, Nature, PLOS ONE). Click any venue to see all papers from it. No schema changes — venue is already a string property on Paper nodes.

---

## Backend

### New router: `backend/routers/venues.py`

Register in `main.py` as `app.include_router(venues_router)`.

```
GET /venues
  Returns all venues in the library, sorted by paper count.
  Query params:
    min_count: int = 1    (exclude venues with fewer papers)
    q: str = ""           (filter venue names containing this string)

  Cypher:
    MATCH (p:Paper)
    WHERE p.venue IS NOT NULL AND p.venue <> ""
    WITH p.venue AS name,
         count(p) AS count,
         collect(DISTINCT p.year) AS years
    WHERE count >= $min_count
    RETURN name, count, years
    ORDER BY count DESC

  Response: [{ "name": str, "count": int, "years": list[int] }]

GET /venues/{venue_name}/papers
  Returns all papers from a venue (URL-encoded name).
  Cypher:
    MATCH (p:Paper {venue: $name})
    RETURN p ORDER BY p.year DESC, p.title

  Response: list[PaperOut]   (same schema as GET /papers)
  404 if no papers found for this venue.
```

**Pydantic schema** (add to `models/schemas.py`):
```python
class VenueOut(BaseModel):
    name: str
    count: int
    years: list[int]
```

---

## Frontend

### New page: `frontend/src/pages/Venues.tsx`

**Route:** `/venues` — add to `App.tsx` router and NavBar.

**Layout:**
```
┌─ NavBar ──────────────────────────────────────────────┐
│ Venues                                                │
├───────────────────────────────────────────────────────┤
│  [Search venues...]                                   │
│                                                       │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ │
│  │ NeurIPS  │ │  ICML    │ │  Nature  │ │  arXiv   │ │
│  │ 14 papers│ │ 9 papers │ │ 6 papers │ │ 4 papers │ │
│  │2020–2024 │ │2021–2024 │ │2019–2023 │ │2023–2024 │ │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ │
│  ...                                                  │
│                                                       │
│  [No venue information stored for X papers]  (footer) │
└───────────────────────────────────────────────────────┘
```

**Venue card:**
- Name (bold, large)
- Paper count
- Year range (min–max of years list)
- Type chip: auto-detect "Conference" vs "Journal" vs "Preprint"
  - Heuristic: if name contains "arxiv" → Preprint; if name contains common conference strings (NeurIPS, ICML, ICLR, CVPR, ECCV, ACL, EMNLP, etc.) → Conference; else → Journal

**On click:** open a side panel (or navigate to `/venues/{name}`) showing the paper list for that venue, using the same PaperCard component from Library.

### Search / filter
- Text filter on venue name (client-side — filter already-loaded list)
- Sort by: Paper count (default), Venue name (A–Z), Most recent

### State
```ts
const [venues, setVenues] = useState<VenueOut[]>([])
const [filter, setFilter] = useState("")
const [selectedVenue, setSelectedVenue] = useState<string | null>(null)
const [venuePapers, setVenuePapers] = useState<Paper[]>([])
```

### TypeScript types (add to `types/index.ts`)
```ts
interface VenueOut {
  name: string
  count: number
  years: number[]
}
```

### API helpers (add to `client.ts`)
```ts
export async function listVenues(minCount?: number, q?: string): Promise<VenueOut[]>
export async function getVenuePapers(venueName: string): Promise<Paper[]>
```

---

## Bonus: venue badge on PaperCard

Once the venues page exists, add a small venue chip to `frontend/src/components/PaperCard.tsx`:
```
[NeurIPS 2023]
```
— clicking it navigates to `/venues/NeurIPS` with that venue pre-selected.

---

## Done when
- [ ] `GET /venues` returns all venues with counts and year ranges
- [ ] `GET /venues/{name}/papers` returns papers for a venue
- [ ] Venues page reachable from NavBar
- [ ] Venue cards show count and year range
- [ ] Client-side search filter works
- [ ] Clicking a venue shows its papers (panel or sub-page)
- [ ] Papers with no venue stored are excluded (handled silently)
- [ ] Venue chip on PaperCard (bonus)
