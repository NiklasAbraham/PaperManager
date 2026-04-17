# T12 — Claude Summarization

**Phase:** 3 — File handling + AI
**Depends on:** T01, T10
**Touches:** `backend/services/ai.py`

## Goal
Send extracted PDF text to Claude and get back a structured summary.
This fires automatically when a paper is ingested.

## ai.py — summarize

```python
def summarize_paper(text: str, title: str = "") -> str:
    # Sends the paper text to Claude
    # Returns a markdown summary string
```

### Prompt design

```
You are a research assistant helping to summarize academic papers.

Given the following paper text, write a concise summary covering:
1. **Problem**: What problem does this paper address?
2. **Method**: What approach or method do they use?
3. **Key findings**: What are the main results or contributions?
4. **Relevance**: Who would benefit from reading this?

Keep the summary under 300 words. Use plain language where possible.

Paper title: {title}

Paper text (first 8000 words):
{text[:40000]}
```

### Notes on text truncation
- Claude has a large context window but we truncate to ~40k chars (≈8k words)
- For most papers the abstract + intro + conclusion covers most of this
- Full text is still stored for chat (T14)

## Done when
- [ ] `summarize_paper(text)` returns a non-empty markdown string
- [ ] Summary has the 4 expected sections
- [ ] Works on a real extracted paper text
- [ ] Handles empty text gracefully (returns a note that text was unavailable)

## Tests
`backend/tests/test_ai.py`
- Mark as `@pytest.mark.integration` (hits real Claude API)
- Short text input → returns summary with expected structure
- Empty text → returns a graceful fallback string, does not crash
