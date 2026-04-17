from fastapi import APIRouter, HTTPException, status
from db.connection import get_driver
from db.queries.people import (
    create_person, get_person, list_people,
    link_author, link_involves, link_specializes,
    get_papers_by_person, get_specialties,
)
from db.queries.topics import get_or_create_topic
from models.schemas import PersonCreate, PersonOut, AuthorLink, InvolvesLink, SpecialtyLink

router = APIRouter(tags=["people"])
people_router = APIRouter(prefix="/people", tags=["people"])
papers_router = APIRouter(prefix="/papers", tags=["people"])


@people_router.post("", response_model=PersonOut, status_code=status.HTTP_201_CREATED)
def create(body: PersonCreate):
    return create_person(get_driver(), body.model_dump())


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
