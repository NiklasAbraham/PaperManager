import logging
from fastapi import APIRouter, HTTPException, status
from db.connection import get_driver
from db.queries.topics import (
    get_or_create_topic, list_topics, link_paper_topic, unlink_paper_topic,
    papers_by_topic, link_related_topics, get_topics_for_paper,
)
from db.queries.papers import get_paper
from models.schemas import TopicBody, PaperOut

log = logging.getLogger(__name__)

topics_router = APIRouter(prefix="/topics", tags=["topics"])
papers_router = APIRouter(prefix="/papers", tags=["topics"])


@topics_router.get("")
def list_all():
    return list_topics(get_driver())


@topics_router.post("", status_code=status.HTTP_201_CREATED)
def create_topic(body: TopicBody):
    return get_or_create_topic(get_driver(), body.name)


@topics_router.get("/{name}/papers", response_model=list[PaperOut])
def papers(name: str):
    return papers_by_topic(get_driver(), name)


@topics_router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_topic(name: str):
    with get_driver().session() as session:
        session.run("MATCH (t:Topic {name: $name}) DETACH DELETE t", name=name)


@topics_router.patch("/{name}")
def rename_topic(name: str, body: dict):
    new_name = body.get("name", "").strip()
    if not new_name:
        return {"error": "name required"}
    with get_driver().session() as session:
        result = session.run(
            "MATCH (t:Topic {name: $old}) SET t.name = $new RETURN t",
            old=name, new=new_name
        ).single()
    return dict(result["t"]) if result else {}


@topics_router.post("/{name_a}/related/{name_b}", status_code=201)
def relate(name_a: str, name_b: str):
    link_related_topics(get_driver(), name_a, name_b)
    return {"related": [name_a, name_b]}


@papers_router.get("/{paper_id}/topics")
def list_paper_topics(paper_id: str):
    return get_topics_for_paper(get_driver(), paper_id)


@papers_router.post("/{paper_id}/topics/suggest")
def suggest(paper_id: str):
    """Use Claude Haiku to suggest topics for an existing paper."""
    from services.ai import suggest_topics
    driver = get_driver()
    paper = get_paper(driver, paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    try:
        topics = suggest_topics(
            title=paper.get("title", ""),
            abstract=paper.get("abstract", "") or "",
            summary=paper.get("summary", "") or "",
        )
        return {"topics": topics}
    except Exception as exc:
        log.warning("Topic suggestion failed | %s", exc)
        raise HTTPException(status_code=502, detail=f"AI topic suggestion failed: {exc}")


@papers_router.post("/{paper_id}/topics", status_code=201)
def add_topic(paper_id: str, body: TopicBody):
    topic = link_paper_topic(get_driver(), paper_id, body.name)
    return {"paper_id": paper_id, "topic": topic}


@papers_router.delete("/{paper_id}/topics/{name}", status_code=204)
def remove_topic(paper_id: str, name: str):
    unlink_paper_topic(get_driver(), paper_id, name)
