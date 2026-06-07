"""Merge Manager — find near-duplicate papers and merge them.

Scan endpoint:   POST /merge/scan?model=ollama|claude
Execute endpoint: POST /merge/execute
"""
from __future__ import annotations

import difflib
import json
import logging
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db.connection import get_driver

log = logging.getLogger(__name__)

router = APIRouter(prefix="/merge", tags=["merge"])

_PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"
_BATCH_SIZE = 30  # max pairs per Ollama/Claude call — keeps context window safe


# ── Schemas ────────────────────────────────────────────────────────────────

class DuplicatePair(BaseModel):
    paper_a: dict
    paper_b: dict
    similarity: float   # 0–1
    reason: str         # human-readable explanation


class ScanResult(BaseModel):
    pairs: list[DuplicatePair]
    total_papers: int


class MergeExecuteRequest(BaseModel):
    keep_id: str
    remove_id: str


class MergeExecuteResult(BaseModel):
    kept_id: str
    removed_id: str
    relationships_moved: int


# ── Helpers ────────────────────────────────────────────────────────────────

def _title_similarity(a: str, b: str) -> float:
    """Normalised SequenceMatcher ratio on lower-cased, whitespace-collapsed titles."""
    a = " ".join(a.lower().split())
    b = " ".join(b.lower().split())
    return difflib.SequenceMatcher(None, a, b).ratio()


def _load_prompt_template() -> str:
    try:
        return (_PROMPTS_DIR / "merge_scan.txt").read_text(encoding="utf-8")
    except FileNotFoundError:
        # Inline fallback so the router never hard-fails
        return (
            "You are a research librarian checking for duplicate paper entries.\n"
            "Below are {n_pairs} pairs of paper titles with high string similarity.\n"
            "For each pair decide if they refer to the same paper.\n"
            "Return ONLY a JSON array: "
            '[{{"idx": <index>, "same": true|false, "reason": "<one sentence>"}}]\n\n'
            "Pairs:\n{pairs_block}"
        )


def _build_pairs_block(batch: list[tuple[dict, dict, float]]) -> str:
    lines = []
    for i, (a, b, _) in enumerate(batch):
        lines.append(f'{i}: A: "{a.get("title", "")}" | B: "{b.get("title", "")}"')
    return "\n".join(lines)


def _parse_batch_response(raw: str, batch: list[tuple[dict, dict, float]]) -> list[DuplicatePair]:
    """Parse a JSON array response from the model and return confirmed duplicate pairs."""
    results: list[DuplicatePair] = []
    try:
        m = re.search(r"\[.*\]", raw, re.DOTALL)
        items = json.loads(m.group()) if m else []
    except Exception:
        items = []

    for item in items:
        idx = item.get("idx")
        if idx is None or not isinstance(idx, int) or idx >= len(batch):
            continue
        if not item.get("same", False):
            continue
        a, b, sim = batch[idx]
        results.append(DuplicatePair(
            paper_a=_slim(a), paper_b=_slim(b),
            similarity=round(sim, 3),
            reason=str(item.get("reason", f"Title similarity {sim:.0%}")),
        ))
    return results


def _verify_with_litellm(pairs: list[tuple[dict, dict, float]], model: str) -> list[DuplicatePair]:
    """Batch-verify candidate pairs with LiteLLM (chunked to _BATCH_SIZE)."""
    from services.litellm_client import chat_completion, resolve_chat_model

    template = _load_prompt_template()
    results: list[DuplicatePair] = []
    resolved = resolve_chat_model(model)

    for chunk_start in range(0, len(pairs), _BATCH_SIZE):
        batch = pairs[chunk_start: chunk_start + _BATCH_SIZE]
        prompt = template.format(
            n_pairs=len(batch),
            pairs_block=_build_pairs_block(batch),
        )
        try:
            raw = chat_completion(
                messages=[{"role": "user", "content": prompt}],
                model=resolved,
            )
            results.extend(_parse_batch_response(raw, batch))
            log.info("Merge scan batch %d–%d: LiteLLM verified", chunk_start, chunk_start + len(batch) - 1)
        except Exception as exc:
            log.warning("LiteLLM batch verification failed (chunk %d): %s — falling back to similarity", chunk_start, exc)
            results.extend(_no_ai_pairs(batch))

    return results


def _verify_with_claude(pairs: list[tuple[dict, dict, float]]) -> list[DuplicatePair]:
    """Batch-verify candidate pairs with Claude Haiku (chunked to _BATCH_SIZE)."""
    import anthropic
    from config import settings as cfg
    from services.user_ai_config import get_effective_ai_config

    try:
        ai_cfg = get_effective_ai_config()
        personal_key = (ai_cfg.get("anthropic_api_key") or "").strip()
        if not personal_key:
            return _verify_with_litellm(pairs, cfg.litellm_model)
        client = anthropic.Anthropic(api_key=personal_key)
    except Exception:
        return _verify_with_litellm(pairs, cfg.litellm_model)

    template = _load_prompt_template()
    results: list[DuplicatePair] = []

    for chunk_start in range(0, len(pairs), _BATCH_SIZE):
        batch = pairs[chunk_start: chunk_start + _BATCH_SIZE]
        prompt = template.format(
            n_pairs=len(batch),
            pairs_block=_build_pairs_block(batch),
        )
        try:
            msg = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=_BATCH_SIZE * 40,   # ~40 tokens per item
                messages=[{"role": "user", "content": prompt}],
            )
            raw = msg.content[0].text.strip()
            results.extend(_parse_batch_response(raw, batch))
            log.info("Merge scan batch %d–%d: Claude verified", chunk_start, chunk_start + len(batch) - 1)
        except Exception as exc:
            log.warning("Claude batch verification failed (chunk %d): %s — falling back to similarity", chunk_start, exc)
            results.extend(_no_ai_pairs(batch))

    return results


def _no_ai_pairs(pairs: list[tuple[dict, dict, float]]) -> list[DuplicatePair]:
    """Return all candidates as confirmed (no AI check — similarity only)."""
    return [
        DuplicatePair(
            paper_a=_slim(a), paper_b=_slim(b),
            similarity=round(sim, 3),
            reason=f"Title similarity {sim:.0%}",
        )
        for a, b, sim in pairs
    ]


def _slim(p: dict) -> dict:
    """Return a small subset of paper fields safe to send to the frontend."""
    return {
        "id": p.get("id"),
        "title": p.get("title"),
        "year": p.get("year"),
        "doi": p.get("doi"),
        "abstract": (p.get("abstract") or "")[:300],
        "metadata_source": p.get("metadata_source"),
        "drive_file_id": p.get("drive_file_id"),
    }


# ── Endpoints ──────────────────────────────────────────────────────────────

@router.post("/scan", response_model=ScanResult)
def scan_duplicates(model: str = "litellm"):
    """
    Compare all paper titles and return candidate duplicate pairs.

    model: "litellm" (default) | "ollama" (alias) | "claude" | "none" (raw similarity only)
    """
    from config import settings as cfg

    driver = get_driver()
    with driver.session() as session:
        result = session.run(
            "MATCH (p:Paper) RETURN p.id AS id, p.title AS title, "
            "p.year AS year, p.doi AS doi, p.abstract AS abstract, "
            "p.metadata_source AS metadata_source, p.drive_file_id AS drive_file_id"
        )
        papers = [dict(r) for r in result]

    papers = [p for p in papers if p.get("title") and p["title"].strip()]
    total = len(papers)
    log.info("Merge scan: %d papers", total)

    # O(n²) similarity check — fine for typical library sizes (< 5 000 papers)
    THRESHOLD = 0.82
    candidates: list[tuple[dict, dict, float]] = []
    seen: set[frozenset] = set()

    for i in range(len(papers)):
        for j in range(i + 1, len(papers)):
            a, b = papers[i], papers[j]
            key = frozenset([a["id"], b["id"]])
            if key in seen:
                continue
            sim = _title_similarity(a["title"], b["title"])
            if sim >= THRESHOLD:
                seen.add(key)
                candidates.append((a, b, sim))

    # Sort by descending similarity
    candidates.sort(key=lambda x: x[2], reverse=True)
    log.info("Merge scan: %d candidate pairs (threshold=%.0f%%)", len(candidates), THRESHOLD * 100)

    # AI verification
    if not candidates:
        return ScanResult(pairs=[], total_papers=total)

    if model in ("litellm", "ollama"):
        pairs = _verify_with_litellm(candidates, cfg.litellm_model)
    elif model == "claude":
        pairs = _verify_with_claude(candidates)
    else:
        pairs = _no_ai_pairs(candidates)

    return ScanResult(pairs=pairs, total_papers=total)


@router.post("/execute", response_model=MergeExecuteResult)
def execute_merge(body: MergeExecuteRequest):
    """
    Merge two papers: move all relationships from remove_id → keep_id, then delete remove_id.

    Moves:
      - AUTHORED_BY (paper→person)
      - TAGGED (paper→tag)
      - ABOUT (paper→topic)
      - Project CONTAINS (project→paper)
      - CITES outgoing (paper→paper)
      - CITES incoming (paper→paper)
      - Note ABOUT (note→paper)
      - INVOLVES (person→paper)
    """
    driver = get_driver()

    keep_id = body.keep_id
    remove_id = body.remove_id

    if keep_id == remove_id:
        raise HTTPException(status_code=400, detail="keep_id and remove_id must differ")

    with driver.session() as session:
        # Verify both exist
        k = session.run("MATCH (p:Paper {id: $id}) RETURN p.id", id=keep_id).single()
        r = session.run("MATCH (p:Paper {id: $id}) RETURN p.id", id=remove_id).single()
        if not k:
            raise HTTPException(status_code=404, detail=f"Paper to keep not found: {keep_id}")
        if not r:
            raise HTTPException(status_code=404, detail=f"Paper to remove not found: {remove_id}")

        moved = 0

        # AUTHORED_BY: (remove)-[:AUTHORED_BY]->(person)  →  (keep)-[:AUTHORED_BY]->(person)
        res = session.run("""
            MATCH (remove:Paper {id: $rid})-[rel:AUTHORED_BY]->(person:Person)
            MATCH (keep:Paper {id: $kid})
            MERGE (keep)-[:AUTHORED_BY]->(person)
            DELETE rel
            RETURN count(rel) AS n
        """, rid=remove_id, kid=keep_id)
        moved += res.single()["n"]

        # TAGGED: (remove)-[:TAGGED]->(tag)
        res = session.run("""
            MATCH (remove:Paper {id: $rid})-[rel:TAGGED]->(tag:Tag)
            MATCH (keep:Paper {id: $kid})
            MERGE (keep)-[:TAGGED]->(tag)
            DELETE rel
            RETURN count(rel) AS n
        """, rid=remove_id, kid=keep_id)
        moved += res.single()["n"]

        # ABOUT (topic): (remove)-[:ABOUT]->(topic)
        res = session.run("""
            MATCH (remove:Paper {id: $rid})-[rel:ABOUT]->(topic:Topic)
            MATCH (keep:Paper {id: $kid})
            MERGE (keep)-[:ABOUT]->(topic)
            DELETE rel
            RETURN count(rel) AS n
        """, rid=remove_id, kid=keep_id)
        moved += res.single()["n"]

        # Project CONTAINS: (project)-[:CONTAINS]->(remove)
        res = session.run("""
            MATCH (project:Project)-[rel:CONTAINS]->(remove:Paper {id: $rid})
            MATCH (keep:Paper {id: $kid})
            MERGE (project)-[:CONTAINS]->(keep)
            DELETE rel
            RETURN count(rel) AS n
        """, rid=remove_id, kid=keep_id)
        moved += res.single()["n"]

        # CITES outgoing: (remove)-[:CITES]->(cited)
        res = session.run("""
            MATCH (remove:Paper {id: $rid})-[rel:CITES]->(cited:Paper)
            WHERE cited.id <> $kid
            MATCH (keep:Paper {id: $kid})
            MERGE (keep)-[:CITES]->(cited)
            DELETE rel
            RETURN count(rel) AS n
        """, rid=remove_id, kid=keep_id)
        moved += res.single()["n"]

        # CITES incoming: (citer)-[:CITES]->(remove)
        res = session.run("""
            MATCH (citer:Paper)-[rel:CITES]->(remove:Paper {id: $rid})
            WHERE citer.id <> $kid
            MATCH (keep:Paper {id: $kid})
            MERGE (citer)-[:CITES]->(keep)
            DELETE rel
            RETURN count(rel) AS n
        """, rid=remove_id, kid=keep_id)
        moved += res.single()["n"]

        # Note ABOUT: (note)-[:ABOUT]->(remove)
        res = session.run("""
            MATCH (note:Note)-[rel:ABOUT]->(remove:Paper {id: $rid})
            MATCH (keep:Paper {id: $kid})
            MERGE (note)-[:ABOUT]->(keep)
            DELETE rel
            RETURN count(rel) AS n
        """, rid=remove_id, kid=keep_id)
        moved += res.single()["n"]

        # INVOLVES: (person)-[:INVOLVES]->(remove)
        res = session.run("""
            MATCH (person:Person)-[rel:INVOLVES]->(remove:Paper {id: $rid})
            MATCH (keep:Paper {id: $kid})
            MERGE (person)-[:INVOLVES]->(keep)
            DELETE rel
            RETURN count(rel) AS n
        """, rid=remove_id, kid=keep_id)
        moved += res.single()["n"]

        # Delete the removed paper node (and any remaining direct rels)
        session.run("""
            MATCH (p:Paper {id: $rid})
            DETACH DELETE p
        """, rid=remove_id)

        log.info("Merge done | kept=%s removed=%s moved=%d rels", keep_id, remove_id, moved)

    return MergeExecuteResult(kept_id=keep_id, removed_id=remove_id, relationships_moved=moved)
