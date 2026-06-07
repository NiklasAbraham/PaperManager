import json
import logging
from fastapi import APIRouter
from typing import Optional
from pydantic import BaseModel
from db.connection import get_driver
from db.queries.search import search_papers

log = logging.getLogger(__name__)
router = APIRouter(prefix="/search", tags=["search"])


@router.get("")
def search(
    q: Optional[str] = None,
    tag: Optional[str] = None,
    topic: Optional[str] = None,
    project_id: Optional[str] = None,
    person_id: Optional[str] = None,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    reading_status: Optional[str] = None,
    bookmarked: Optional[bool] = None,
    skip: int = 0,
    limit: int = 20,
):
    return search_papers(
        get_driver(),
        q=q,
        tag=tag,
        topic=topic,
        project_id=project_id,
        person_id=person_id,
        year_min=year_min,
        year_max=year_max,
        reading_status=reading_status,
        bookmarked=bookmarked,
        skip=skip,
        limit=limit,
    )


class InterpretBody(BaseModel):
    query: str


@router.post("/interpret")
def interpret_search(body: InterpretBody):
    """Use Ollama to parse a natural language query into structured search filters."""
    from config import settings as _settings

    driver = get_driver()

    # Fetch available filter values to anchor Ollama's choices
    with driver.session() as s:
        tags = [r["name"] for r in s.run(
            "MATCH (t:Tag)<-[:TAGGED]-(:Paper) RETURN t.name AS name, count(*) AS c "
            "ORDER BY c DESC LIMIT 40"
        )]
        topics = [r["name"] for r in s.run(
            "MATCH (t:Topic)<-[:ABOUT]-(:Paper) RETURN t.name AS name ORDER BY t.name LIMIT 40"
        )]
        venues = [r["venue"] for r in s.run(
            "MATCH (p:Paper) WHERE p.venue IS NOT NULL AND trim(p.venue) <> '' "
            "RETURN p.venue AS venue, count(*) AS c ORDER BY c DESC LIMIT 30"
        )]

    prompt = (
        "You are a search filter assistant for an academic paper library.\n"
        "Parse the natural language query below into structured filters.\n\n"
        f"Known tags (pick at most one if relevant): {', '.join(tags)}\n"
        f"Known topics (pick at most one if relevant): {', '.join(topics)}\n"
        f"Known venues (pick at most one if relevant): {', '.join(venues)}\n\n"
        f'Query: "{body.query}"\n\n'
        "Return ONLY valid JSON with these exact keys (use null when not applicable):\n"
        '{"keyword": null, "tag": null, "topic": null, "venue": null, '
        '"year_min": null, "year_max": null}'
    )

    try:
        from services.litellm_client import chat_completion

        raw = chat_completion(
            messages=[{"role": "user", "content": prompt}],
            json_mode=True,
        )
        parsed = json.loads(raw)
        result = {
            "keyword": parsed.get("keyword") or None,
            "tag":     parsed.get("tag")     or None,
            "topic":   parsed.get("topic")   or None,
            "venue":   parsed.get("venue")   or None,
            "year_min": int(parsed["year_min"]) if parsed.get("year_min") else None,
            "year_max": int(parsed["year_max"]) if parsed.get("year_max") else None,
        }
        # Validate against known values to avoid hallucinations
        if result["tag"]   and result["tag"]   not in tags:   result["tag"]   = None
        if result["topic"] and result["topic"] not in topics: result["topic"] = None
        if result["venue"] and result["venue"] not in venues: result["venue"] = None
        log.debug("Search interpret result: %s", result)
        return result
    except Exception as exc:
        log.warning("Search interpret failed: %s", exc)
        return {"keyword": body.query, "tag": None, "topic": None,
                "venue": None, "year_min": None, "year_max": None}
