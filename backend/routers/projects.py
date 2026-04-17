from fastapi import APIRouter, HTTPException, status
from db.connection import get_driver
from db.queries.projects import (
    create_project, get_project, list_projects, update_project,
    delete_project, add_paper_to_project, remove_paper_from_project,
    get_project_papers, link_projects,
)
from models.schemas import ProjectCreate, ProjectUpdate, ProjectOut, ProjectPaperLink

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def create(body: ProjectCreate):
    return create_project(get_driver(), body.model_dump())


@router.get("")
def list_all():
    return list_projects(get_driver())


@router.get("/{project_id}")
def get_one(project_id: str):
    project = get_project(get_driver(), project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    papers = get_project_papers(get_driver(), project_id)
    return {**project, "papers": papers}


@router.patch("/{project_id}", response_model=ProjectOut)
def update(project_id: str, body: ProjectUpdate):
    data = {k: v for k, v in body.model_dump().items() if v is not None}
    project = update_project(get_driver(), project_id, data)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(project_id: str):
    if not delete_project(get_driver(), project_id):
        raise HTTPException(status_code=404, detail="Project not found")


@router.post("/{project_id}/papers", status_code=status.HTTP_201_CREATED)
def add_paper(project_id: str, body: ProjectPaperLink):
    if not get_project(get_driver(), project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    add_paper_to_project(get_driver(), body.paper_id, project_id)
    return {"project_id": project_id, "paper_id": body.paper_id}


@router.delete("/{project_id}/papers/{paper_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_paper(project_id: str, paper_id: str):
    remove_paper_from_project(get_driver(), paper_id, project_id)


@router.post("/{project_a_id}/related/{project_b_id}", status_code=status.HTTP_201_CREATED)
def relate(project_a_id: str, project_b_id: str):
    link_projects(get_driver(), project_a_id, project_b_id)
    return {"related": [project_a_id, project_b_id]}
