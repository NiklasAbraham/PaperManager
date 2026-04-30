from fastapi import APIRouter, HTTPException, Response

from db.connection import get_driver
from db.queries.annotations import (
    list_annotations,
    create_annotation,
    update_annotation,
    delete_annotation,
)
from models.schemas import AnnotationCreate, AnnotationUpdate, AnnotationOut

router = APIRouter(prefix="/papers", tags=["annotations"])


@router.get("/{paper_id}/annotations", response_model=list[AnnotationOut])
def get_annotations(paper_id: str):
    return list_annotations(get_driver(), paper_id)


@router.post("/{paper_id}/annotations", response_model=AnnotationOut, status_code=201)
def add_annotation(paper_id: str, body: AnnotationCreate):
    return create_annotation(
        get_driver(),
        paper_id,
        body.page_number,
        body.highlighted_text,
        body.color,
        body.note,
        body.position_json,
    )


@router.patch("/{paper_id}/annotations/{annotation_id}", response_model=AnnotationOut)
def edit_annotation(paper_id: str, annotation_id: str, body: AnnotationUpdate):
    result = update_annotation(get_driver(), annotation_id, body.note, body.color)
    if result is None:
        raise HTTPException(status_code=404, detail="Annotation not found")
    return result


@router.delete("/{paper_id}/annotations/{annotation_id}", status_code=204)
def remove_annotation(paper_id: str, annotation_id: str):
    delete_annotation(get_driver(), annotation_id)
    return Response(status_code=204)
