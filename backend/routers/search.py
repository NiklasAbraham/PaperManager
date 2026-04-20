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
