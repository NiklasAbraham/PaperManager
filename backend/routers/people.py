from fastapi import APIRouter, HTTPException, Query, status
from db.connection import get_driver
from db.queries.people import (
    create_person, get_person, list_people, delete_person,
    link_author, link_involves, link_specializes,
    unlink_author, unlink_involves,
    get_papers_by_person, get_specialties,
)
from models.schemas import PersonCreate as PersonUpdate
from db.queries.topics import get_or_create_topic
from models.schemas import PersonCreate, PersonOut, AuthorLink, InvolvesLink, SpecialtyLink

router = APIRouter(tags=["people"])
people_router = APIRouter(prefix="/people", tags=["people"])
papers_router = APIRouter(prefix="/papers", tags=["people"])


@people_router.post("", response_model=PersonOut, status_code=status.HTTP_201_CREATED)
def create(body: PersonCreate):
    return create_person(get_driver(), body.model_dump())


@people_router.post("/get-or-create", response_model=PersonOut)
def get_or_create(body: PersonCreate):
    """Return existing person matched by name (case-insensitive) or create a new one."""
    from db.queries.people import get_or_create_person
    return get_or_create_person(get_driver(), body.name)


@people_router.get("", response_model=list[PersonOut])
def list_all():
    return list_people(get_driver())


@people_router.get("/{person_id}")
def get_one(person_id: str):
    person = get_person(get_driver(), person_id)
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")
    papers = get_papers_by_person(get_driver(), person_id)
    specialties = get_specialties(get_driver(), person_id)
    return {**person, "papers": papers, "specialties": specialties}


@people_router.patch("/{person_id}", response_model=PersonOut)
def update_person(person_id: str, body: PersonUpdate):
    person = get_person(get_driver(), person_id)
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")
    with get_driver().session() as session:
        data = {k: v for k, v in body.model_dump().items() if v is not None}
        result = session.run(
            "MATCH (p:Person {id: $id}) SET p += $props RETURN p",
            id=person_id, props=data
        ).single()
    return dict(result["p"]) if result else person


@people_router.delete("/{person_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_person(person_id: str):
    if not delete_person(get_driver(), person_id):
        raise HTTPException(status_code=404, detail="Person not found")


@people_router.post("/{person_id}/specialties", status_code=status.HTTP_201_CREATED)
def add_specialty(person_id: str, body: SpecialtyLink):
    if not get_person(get_driver(), person_id):
        raise HTTPException(status_code=404, detail="Person not found")
    topic = get_or_create_topic(get_driver(), body.topic_name)
    link_specializes(get_driver(), person_id, topic["id"])
    return {"person_id": person_id, "topic": topic}


@papers_router.post("/{paper_id}/authors", status_code=status.HTTP_201_CREATED)
def add_author(paper_id: str, body: AuthorLink):
    link_author(get_driver(), paper_id, body.person_id)
    return {"paper_id": paper_id, "person_id": body.person_id, "rel": "AUTHORED_BY"}


@papers_router.post("/{paper_id}/involves", status_code=status.HTTP_201_CREATED)
def add_involves(paper_id: str, body: InvolvesLink):
    link_involves(get_driver(), paper_id, body.person_id, body.role)
    return {"paper_id": paper_id, "person_id": body.person_id, "role": body.role}


@papers_router.delete("/{paper_id}/authors/{person_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_author(paper_id: str, person_id: str):
    unlink_author(get_driver(), paper_id, person_id)


@papers_router.delete("/{paper_id}/involves/{person_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_involves(paper_id: str, person_id: str, role: str | None = Query(None)):
    unlink_involves(get_driver(), paper_id, person_id, role)
