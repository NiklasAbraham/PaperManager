from fastapi import APIRouter
from db.connection import get_driver
from db.queries.tags import tag_paper, untag_paper, list_tags, papers_by_tag
from models.schemas import TagBody, PaperOut

tags_router = APIRouter(prefix="/tags", tags=["tags"])
papers_router = APIRouter(prefix="/papers", tags=["tags"])


@tags_router.get("")
def list_all():
    return list_tags(get_driver())


@tags_router.get("/{name}/papers", response_model=list[PaperOut])
def papers(name: str):
    return papers_by_tag(get_driver(), name)


@papers_router.post("/{paper_id}/tags", status_code=201)
def add_tag(paper_id: str, body: TagBody):
    tag = tag_paper(get_driver(), paper_id, body.name)
    return {"paper_id": paper_id, "tag": tag}


@papers_router.delete("/{paper_id}/tags/{name}", status_code=204)
def remove_tag(paper_id: str, name: str):
    untag_paper(get_driver(), paper_id, name)
