# T28 — Claim / Hypothesis Extractor

**Phase:** 7 — Discovery & Intelligence
**Depends on:** T04 (schema), T05, T13
**Touches:** `backend/db/schema.py`, new `backend/db/queries/claims.py`, new `backend/routers/claims.py`, `backend/services/ai.py`, `backend/routers/papers.py` (upload pipeline), new `prompts/claims.txt`, `frontend/src/pages/PaperDetail.tsx`

## Goal
On upload, Claude Haiku automatically extracts the key claims, hypotheses, findings, and methods from each paper as structured nodes in Neo4j. Browsable in a new "Claims" tab on the paper detail page. Searchable across the whole library.

---

## Backend

### Neo4j schema — `backend/db/schema.py`

Add on startup (idempotent):
```cypher
CREATE CONSTRAINT claim_id_unique IF NOT EXISTS FOR (c:Claim) REQUIRE c.id IS UNIQUE
CREATE FULLTEXT INDEX claim_search IF NOT EXISTS FOR (c:Claim) ON EACH [c.text]
```

### New queries: `backend/db/queries/claims.py`

```python
from uuid import uuid4

CLAIM_TYPES = {"claim", "hypothesis", "finding", "method", "limitation"}

def create_claims(driver, paper_id: str, claims: list[dict]) -> list[dict]:
    """
    claims: [{"text": str, "type": str}]
    Creates Claim nodes and (Paper)-[:HAS_CLAIM]->(Claim) relationships.
    Uses MERGE on (Claim {id}) — safe to call idempotently if same id reused.
    """
    created = []
    with driver.session() as session:
        for c in claims:
            claim_id = str(uuid4())
            c_type = c.get("type", "claim")
            if c_type not in CLAIM_TYPES:
                c_type = "claim"
            result = session.run(
                """
                MATCH (p:Paper {id: $paper_id})
                CREATE (c:Claim {id: $id, text: $text, type: $type})
                CREATE (p)-[:HAS_CLAIM]->(c)
                RETURN c
                """,
                paper_id=paper_id, id=claim_id,
                text=c["text"].strip(), type=c_type,
            )
            record = result.single()
            if record:
                created.append(dict(record["c"]))
    return created

def get_paper_claims(driver, paper_id: str) -> list[dict]:
    """
    MATCH (p:Paper {id: $id})-[:HAS_CLAIM]->(c:Claim)
    RETURN c ORDER BY c.type, c.text
    """

def delete_paper_claims(driver, paper_id: str) -> int:
    """Delete all Claim nodes for a paper. Returns count deleted."""

def search_claims(driver, query: str, limit: int = 20) -> list[dict]:
    """
    Fulltext search on claim_search index.
    Returns [{claim, paper: {id, title}}]
    """
```

### New prompt: `prompts/claims.txt`

```
Extract the key intellectual contributions from this academic paper.
Return a JSON object with key "claims", a list of objects each with:
  - "text": a single clear sentence stating the claim, finding, method, or hypothesis
  - "type": one of "claim" | "hypothesis" | "finding" | "method" | "limitation"

Rules:
- Maximum 10 items total
- Each text must be self-contained (reader doesn't need to have read the paper)
- Prefer precise, specific statements over vague generalisations
- Include at least one "finding" if the paper is empirical

Paper title: {title}
Paper text (first 8000 words):
{text}

Return ONLY the JSON object, no other text.
```

### New service function in `backend/services/ai.py`

```python
def extract_claims(text: str, title: str) -> list[dict]:
    """
    Uses Claude Haiku to extract claims from paper text.
    Returns list of {"text": str, "type": str}.
    Returns [] on any error (non-fatal — called best-effort on upload).
    """
    import json, re
    if not text or not text.strip():
        return []
    prompt = _load_prompt("claims.txt").format(
        title=title or "(unknown)",
        text=text[:40000],
    )
    try:
        client = _personal_client()
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if not match:
            return []
        data = json.loads(match.group())
        return [c for c in (data.get("claims") or []) if c.get("text")]
    except Exception as exc:
        log.warning("extract_claims failed (non-fatal) | %s", exc)
        return []
```

### Upload pipeline — `backend/routers/papers.py`

In the `POST /papers/upload` handler, after the summary step (step 5), add a best-effort claims step:

```python
# Step 5b: Extract claims (best-effort — skipped for books/lecture decks)
if not is_book:
    try:
        claims_data = extract_claims(raw_text, meta.get("title", ""))
        if claims_data:
            create_claims(driver, paper["id"], claims_data)
            log.info("Claims extracted | count=%d | paper_id=%s", len(claims_data), paper["id"])
    except Exception as exc:
        log.warning("Claim extraction failed (non-fatal) | %s", exc)
```

Also import `extract_claims` from `services.ai` and `create_claims` from `db.queries.claims`.

### New router: `backend/routers/claims.py`

Register in `main.py`.

```
GET /papers/{paper_id}/claims
  Returns { "claims": [{"id", "text", "type"}] }

POST /papers/{paper_id}/claims/extract
  Re-runs extraction and saves results. Deletes existing claims first.
  Returns { "claims": [...], "count": int }
  422 if no raw_text stored.

GET /claims/search?q=
  Fulltext search across all claims. Returns [{claim, paper}].
```

---

## Frontend

### New "Claims" tab in `frontend/src/pages/PaperDetail.tsx`

Add to the existing tab bar.

**Layout:**
```
┌─ Claims & Findings ───────────────────────────────────┐
│                              [Re-extract claims]      │
│                                                       │
│  FINDINGS                                             │
│  • The proposed model achieves 94.2% accuracy on...  │
│  • Training on synthetic data improves...             │
│                                                       │
│  CLAIMS                                               │
│  • Attention mechanisms are sufficient for...         │
│                                                       │
│  METHODS                                              │
│  • Uses a transformer encoder with 12 layers...       │
│                                                       │
│  LIMITATIONS                                          │
│  • Does not evaluate on out-of-domain corpora.        │
│                                                       │
│  [No claims extracted yet — click Re-extract]         │
└───────────────────────────────────────────────────────┘
```

**State:**
- Claims grouped by type, sorted alphabetically within type
- "Re-extract" button calls `POST /papers/{id}/claims/extract`
- Shows spinner while extracting

### TypeScript types (add to `types/index.ts`)
```ts
interface Claim {
  id: string
  text: string
  type: "claim" | "hypothesis" | "finding" | "method" | "limitation"
}
```

### API helpers (add to `client.ts`)
```ts
export async function getPaperClaims(paperId: string): Promise<{ claims: Claim[] }>
export async function extractPaperClaims(paperId: string): Promise<{ claims: Claim[], count: number }>
export async function searchClaims(q: string): Promise<Array<{ claim: Claim, paper: { id: string, title: string } }>>
```

---

## Done when
- [ ] `Claim` nodes created in Neo4j with correct constraints and fulltext index
- [ ] Claims extracted and saved automatically on paper upload
- [ ] `GET /papers/{id}/claims` returns grouped claims
- [ ] `POST /papers/{id}/claims/extract` re-runs extraction
- [ ] "Claims" tab visible in PaperDetail with claims grouped by type
- [ ] "Re-extract" button works and shows updated results
- [ ] Books/lecture decks skip claim extraction
- [ ] `GET /claims/search?q=` returns matching claims with paper context
