# T14 — Chat with a Paper

**Phase:** 3 — File handling + AI
**Depends on:** T05, T12
**Touches:** `backend/services/ai.py`, `backend/routers/papers.py`

## Goal
Ask questions about a specific paper. Claude answers using the paper's extracted text.
Supports multi-turn conversation (history passed from frontend).

## ai.py — chat

```python
def chat_with_paper(
    paper_text: str,
    paper_title: str,
    question: str,
    history: list[dict]   # [{"role": "user"|"assistant", "content": str}]
) -> str:
    # Builds a system prompt with paper context
    # Appends history + new question
    # Returns Claude's answer
```

### System prompt

```
You are a research assistant helping to understand a specific academic paper.
Answer questions about this paper based on its content.
If the answer is not in the paper, say so clearly.

Paper title: {paper_title}

Paper text:
{paper_text[:60000]}
```

## Where is paper_text stored?
- Option A: Store full extracted text as a property on the Paper node in Neo4j
- Option B: Re-download PDF from Drive and re-extract on each chat session

**Decision: Option A** — store `raw_text` on the Paper node.
It's fast, no Drive round-trip needed, and text is already extracted.
Add `raw_text: str` property to Paper (not returned in normal API responses — too large).

## API endpoint

```
POST /papers/{id}/chat
Body: {"question": "...", "history": [{"role": "user", "content": "..."}, ...]}
Response: {"answer": "..."}
```

## Done when
- [ ] `raw_text` is saved on Paper node during ingestion (T13 update)
- [ ] POST /papers/{id}/chat returns a relevant answer
- [ ] Multi-turn: passing history keeps context across questions
- [ ] Paper not found → 404

## Tests
`backend/tests/test_ai.py` (add to existing)
- `@pytest.mark.integration`
- Ask a factual question about a paper with known answer → answer is correct
- Ask something not in the paper → response says it's not covered
- Multi-turn: ask follow-up referencing previous answer → coherent response
