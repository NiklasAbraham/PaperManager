from fastapi import APIRouter
from typing import Optional
from db.connection import get_driver
from db.queries.search import search_papers

router = APIRouter(prefix="/search", tags=["search"])


@router.get("")
def search(
    q: Optional[str] = None,
    tag: Optional[str] = None,
    topic: Optional[str] = None,
    project_id: Optional[str] = None,
    person_id: Optional[str] = None,
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
        skip=skip,
        limit=limit,
    )
