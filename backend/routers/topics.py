from fastapi import APIRouter
from db.connection import get_driver
from db.queries.topics import (
    list_topics, link_paper_topic, unlink_paper_topic,
    papers_by_topic, link_related_topics,
)
from models.schemas import TopicBody, PaperOut

topics_router = APIRouter(prefix="/topics", tags=["topics"])
papers_router = APIRouter(prefix="/papers", tags=["topics"])


@topics_router.get("")
def list_all():
    return list_topics(get_driver())


@topics_router.get("/{name}/papers", response_model=list[PaperOut])
def papers(name: str):
    return papers_by_topic(get_driver(), name)


@topics_router.post("/{name_a}/related/{name_b}", status_code=201)
def relate(name_a: str, name_b: str):
    link_related_topics(get_driver(), name_a, name_b)
    return {"related": [name_a, name_b]}


@papers_router.post("/{paper_id}/topics", status_code=201)
def add_topic(paper_id: str, body: TopicBody):
    topic = link_paper_topic(get_driver(), paper_id, body.name)
    return {"paper_id": paper_id, "topic": topic}


@papers_router.delete("/{paper_id}/topics/{name}", status_code=204)
def remove_topic(paper_id: str, name: str):
    unlink_paper_topic(get_driver(), paper_id, name)
