# T29 — Research Gap Finder

**Phase:** 7 — Discovery & Intelligence
**Depends on:** T05, T15, web search service (already in `backend/services/web_search.py`)
**Touches:** new `backend/routers/research_gaps.py`, `backend/services/ai.py`, new `prompts/research_gaps.txt`, `frontend/src/pages/Library.tsx` or `frontend/src/pages/Projects.tsx`

## Goal
Given a topic or research question, Claude examines your library (or a specific project), searches the web for the current state of the field, and returns a structured analysis of what's missing — gaps in coverage, unexplored directions, and recommended papers to fill them.

---

## Backend

### New prompt: `prompts/research_gaps.txt`

```
You are a research strategist helping identify gaps in a researcher's reading list.

You have access to a web_search tool — use it to:
1. Find what the current state-of-the-art is in this topic (2024–2025 papers)
2. Identify active sub-areas, key open problems, and recent breakthroughs
3. Find specific papers the researcher is missing

Topic / Research question: {topic}

Researcher's current library on this topic ({n} papers):
{papers_block}

Your analysis should include:
## Coverage Summary
What the current library covers well.

## Identified Gaps
Specific sub-topics or methodologies not represented in the library.
For each gap: why it matters, and 1–2 specific papers to read.

## Recommended Next Reads
Ranked list of 5–10 papers to add, with a one-sentence rationale each.
Format as: **[Title]** (Year) — reason.

## Open Questions
2–3 research questions that are not yet addressed by the papers in the library.
```

### New service function in `backend/services/ai.py`

```python
def find_research_gaps(
    topic: str,
    papers: list[dict],   # list of {title, abstract, summary, year}
) -> str:
    """
    Runs Claude Opus with web_search tool enabled.
    Returns markdown analysis string.
    """
    def _paper_block(p: dict) -> str:
        parts = [f"- **{p.get('title', 'Untitled')}** ({p.get('year', '?')})"]
        if p.get("abstract"):
            parts.append(f"  {p['abstract'][:300]}")
        return "\n".join(parts)

    papers_block = "\n".join(_paper_block(p) for p in papers) or "(no papers in library for this topic)"
    system_prompt = _load_prompt("research_gaps.txt").format(
        topic=topic,
        n=len(papers),
        papers_block=papers_block,
    )
    client = _personal_client()
    return _run_claude_with_tools(
        client,
        "claude-opus-4-6",
        "You are a research strategist with web search capabilities.",
        [{"role": "user", "content": system_prompt}],
        max_tokens=2048,
    )
```

### New router: `backend/routers/research_gaps.py`

Register in `main.py`.

```
POST /research-gaps
Body:
{
  "topic": "self-supervised learning for medical imaging",
  "project_id": "uuid-optional",
  "paper_ids": ["uuid1", ...]   // optional — override which papers to consider
}
Response:
{
  "analysis": "## Coverage Summary\n...",
  "papers_considered": int,
  "topic": str
}

Logic:
1. If paper_ids provided: load those specific papers.
2. Else if project_id provided: load papers in that project.
3. Else: search library for papers related to topic using fulltext search
   (call existing search query with q=topic, limit=30).
4. Call find_research_gaps(topic, papers).
5. Return result.
```

**Pydantic schema** (add to `models/schemas.py`):
```python
class ResearchGapsRequest(BaseModel):
    topic: str
    project_id: str | None = None
    paper_ids: list[str] | None = None

class ResearchGapsResponse(BaseModel):
    analysis: str
    papers_considered: int
    topic: str
```

---

## Frontend

### Where to place it

Two entry points:
1. **Library page** — "Find Research Gaps" button in the top bar (next to other actions)
2. **Projects page** — "Analyze Gaps" button on each project card

Both open the same `ResearchGapPanel` component.

### `ResearchGapPanel` component (new `frontend/src/components/ResearchGapPanel.tsx`)

```
┌─ Research Gap Finder ─────────────────────────────────┐
│  Topic / question:                                    │
│  ┌─────────────────────────────────────────────────┐  │
│  │ self-supervised learning for medical imaging    │  │
│  └─────────────────────────────────────────────────┘  │
│                                                       │
│  Scope: ● Whole library  ○ This project              │
│                                                       │
│  [Analyze]   (searches web + analyses your library)  │
├───────────────────────────────────────────────────────┤
│  Analyzing 14 papers + searching the web...          │
│                                                       │
│  ## Coverage Summary                                  │
│  Your library covers supervised learning well...     │
│                                                       │
│  ## Identified Gaps                                   │
│  **Contrastive pretraining on 3D volumes** ...       │
│  Recommended: SimCLR-Med (2024)                       │
│                                                       │
│  ...                                 [Copy] [Close]  │
└───────────────────────────────────────────────────────┘
```

**State:**
- `topic: string`
- `scope: "library" | "project"`
- `loading: boolean`
- `analysis: string | null`

**Behaviour:**
- While loading: show "Analyzing X papers + searching the web…" (fetch paper count from API response)
- Result rendered as markdown
- "Copy" copies raw markdown to clipboard
- Titles in "Recommended Next Reads" section rendered as links that open the Discover page pre-filled with that title

### API helper (add to `client.ts`)
```ts
export async function findResearchGaps(
  topic: string,
  projectId?: string,
  paperIds?: string[]
): Promise<{ analysis: string; papers_considered: number; topic: string }>
```

---

## Done when
- [ ] `POST /research-gaps` returns structured gap analysis for a given topic
- [ ] Library papers for the topic are found via fulltext search (no topic required to be a Neo4j Topic node)
- [ ] Project scope uses correct paper set
- [ ] Claude performs web searches during analysis (visible in backend logs)
- [ ] Panel opens from Library page and Project page
- [ ] Analysis rendered as formatted markdown
- [ ] Loading state shown with paper count
