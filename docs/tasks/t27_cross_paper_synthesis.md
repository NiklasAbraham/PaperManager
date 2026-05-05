# T27 — Cross-Paper Synthesis

**Phase:** 7 — Discovery & Intelligence
**Depends on:** T05, T14, web search service (already in `backend/services/web_search.py`)
**Touches:** new `backend/routers/synthesis.py`, `backend/services/ai.py`, new `prompts/synthesis.txt`, `frontend/src/pages/Library.tsx` (or a new `Synthesize.tsx`)

## Goal
Select 2–10 papers from your library, ask a question or give a theme (e.g. "compare their approaches to handling class imbalance"), and get a structured synthesis that draws on all selected papers and optionally searches the web for additional context.

---

## Backend

### New prompt: `prompts/synthesis.txt`

```
You are a research synthesis expert. You have been given {n} academic papers.
Your task: {question}

Produce a structured, comparative analysis. Use headers for each major dimension
of comparison. Cite papers by their title when you reference them.
If web context is provided below, use it to add current perspective.

## Papers
{papers_block}
```

### New service function in `backend/services/ai.py`

```python
def synthesize_papers(
    papers: list[dict],        # list of {title, abstract, summary, raw_text (optional)}
    question: str,
    use_web: bool = True,
) -> str:
    """
    Builds a synthesis prompt from the selected papers.
    Each paper contributes its abstract + summary (not full raw_text — too large).
    Optionally appends web context via _fetch_web_context().
    Uses claude-opus-4-6 with WEB_SEARCH_TOOL if use_web=True.
    Returns markdown synthesis string.
    """
    def _paper_block(p: dict) -> str:
        parts = [f"### {p.get('title', 'Untitled')}"]
        if p.get("year"):
            parts[0] += f" ({p['year']})"
        if p.get("abstract"):
            parts.append(f"**Abstract:** {p['abstract'][:1500]}")
        if p.get("summary"):
            parts.append(f"**Summary:** {p['summary'][:2000]}")
        return "\n".join(parts)

    papers_block = "\n\n".join(_paper_block(p) for p in papers)
    prompt = _load_prompt("synthesis.txt").format(
        n=len(papers),
        question=question,
        papers_block=papers_block,
    )

    client = _personal_client()
    if use_web:
        return _run_claude_with_tools(client, "claude-opus-4-6",
                                       "You are a research synthesis expert.", [{"role": "user", "content": prompt}])
    else:
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
```

### New router: `backend/routers/synthesis.py`

Register in `main.py` as `app.include_router(synthesis_router)`.

```
POST /synthesis
Body:
{
  "paper_ids": ["uuid1", "uuid2", ...],   // 2–10
  "question": "Compare their methods for X",
  "use_web": true
}
Response:
{
  "synthesis": "## Comparison\n...",
  "papers_used": [{ "id": ..., "title": ... }]
}

Errors:
  422 — fewer than 2 paper_ids
  422 — more than 10 paper_ids
  404 — any paper_id not found
```

Logic:
1. Load each paper from Neo4j (get_paper). Collect title, abstract, summary.
2. Validate count (2–10).
3. Call `synthesize_papers(papers, question, use_web)`.
4. Return synthesis + list of papers used.

---

## Frontend

### Multi-select mode in `frontend/src/pages/Library.tsx`

Add a "Synthesize" mode toggle (button in top bar):
- When active: each PaperCard shows a checkbox
- Selected papers shown in a sticky bottom bar: "3 papers selected · [Synthesize]"
- Click "Synthesize" opens a slide-in panel or modal

### Synthesis panel / modal

```
┌─ Synthesize Selected Papers ──────────────────────────┐
│  Selected (3): Paper A, Paper B, Paper C              │
│                                                       │
│  Question / Theme:                                    │
│  ┌─────────────────────────────────────────────────┐  │
│  │ Compare their approaches to data augmentation   │  │
│  └─────────────────────────────────────────────────┘  │
│  ☑ Also search the web for additional context        │
│                               [Synthesize]            │
├───────────────────────────────────────────────────────┤
│  ## Comparison                                        │
│  (streaming markdown result...)                       │
│                                                       │
│                       [Copy] [Save as note]           │
└───────────────────────────────────────────────────────┘
```

**"Save as note"** — for each paper in the synthesis, append the synthesis as a note (or create a project note if all papers share a project).

### State in Library.tsx
```ts
const [synthMode, setSynthMode] = useState(false)
const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
const [synthPanelOpen, setSynthPanelOpen] = useState(false)
```

### API helper (add to `client.ts`)
```ts
export async function synthesizePapers(
  paperIds: string[],
  question: string,
  useWeb: boolean
): Promise<{ synthesis: string; papers_used: Array<{id: string; title: string}> }>
```

---

## Done when
- [ ] `POST /synthesis` returns a coherent comparison for 2+ papers
- [ ] 422 returned for < 2 or > 10 papers
- [ ] `use_web: false` works (library-only synthesis)
- [ ] Library page has multi-select mode toggle
- [ ] Synthesis panel opens with selected papers pre-filled
- [ ] Result rendered as markdown
- [ ] "Save as note" saves synthesis to each selected paper's note
