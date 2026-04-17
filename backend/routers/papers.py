from fastapi import APIRouter, HTTPException, UploadFile, File, Form, status
from typing import Optional
from db.connection import get_driver
from db.queries.papers import create_paper, get_paper, list_papers, update_paper, delete_paper
from db.queries.notes import get_paper_note, upsert_note, set_mentions
from db.queries.people import get_or_create_person, link_author
from db.queries.topics import get_or_create_topic, link_paper_topic
from db.queries.projects import add_paper_to_project
from services.note_parser import parse_mentions
from services.pdf_parser import extract_metadata
from services.drive import upload_pdf, get_file_url
from services.ai import summarize_paper, chat_with_paper
from models.schemas import PaperCreate, PaperUpdate, PaperOut, NoteBody, NoteOut, IngestOut, ChatRequest, ChatResponse

router = APIRouter(prefix="/papers", tags=["papers"])


@router.post("/parse")
async def parse_pdf(file: UploadFile = File(...)):
    """Extract metadata from a PDF without saving anything.
    Used by the frontend confirmation modal before the real upload."""
    pdf_bytes = await file.read()
    meta = extract_metadata(pdf_bytes)
    meta.pop("raw_text", None)  # too large for JSON
    return meta


@router.post("", response_model=PaperOut, status_code=status.HTTP_201_CREATED)
def create(body: PaperCreate):
    return create_paper(get_driver(), body.model_dump())


@router.post("/upload", response_model=IngestOut, status_code=status.HTTP_201_CREATED)
async def upload(
    file: UploadFile = File(...),
    title_override: Optional[str] = Form(None),
    project_id: Optional[str] = Form(None),
):
    """Full ingestion pipeline: PDF → metadata → Drive → summary → Neo4j."""
    pdf_bytes = await file.read()

    # Step 1-2: Extract metadata
    meta = extract_metadata(pdf_bytes)
    raw_text = meta.get("raw_text", "")

    # Step 3: Apply title override
    if title_override:
        meta["title"] = title_override

    # Step 4: Upload to Drive
    filename = file.filename or f"{meta['title'][:60]}.pdf"
    try:
        drive_file_id = upload_pdf(pdf_bytes, filename)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Drive upload failed: {exc}")

    # Step 5: Summarize (best-effort — don't fail if Claude is down)
    summary = None
    try:
        summary = summarize_paper(raw_text, meta.get("title", ""))
    except Exception:
        pass

    # Step 6: Save paper to Neo4j
    driver = get_driver()
    paper = create_paper(driver, {
        "title": meta.get("title", ""),
        "year": meta.get("year"),
        "doi": meta.get("doi"),
        "abstract": meta.get("abstract"),
        "summary": summary,
        "drive_file_id": drive_file_id,
        "citation_count": meta.get("citation_count"),
        "metadata_source": meta.get("metadata_source", "heuristic"),
        "raw_text": raw_text,
    })

    # Step 7: Link authors
    authors_saved = []
    for name in meta.get("authors", []):
        if not name:
            continue
        person = get_or_create_person(driver, name)
        link_author(driver, paper["id"], person["id"])
        authors_saved.append(name)

    # Step 8: Link auto-topics (from Semantic Scholar)
    topics_added = []
    for topic_name in meta.get("topics", []):
        if not topic_name:
            continue
        topic = get_or_create_topic(driver, topic_name)
        link_paper_topic(driver, paper["id"], topic["id"])
        topics_added.append(topic_name)

    # Step 9: Link to project if provided
    if project_id:
        try:
            add_paper_to_project(driver, project_id, paper["id"])
        except Exception:
            pass  # project not found — don't fail the whole ingestion

    return {
        **paper,
        "drive_url": get_file_url(drive_file_id),
        "authors": authors_saved,
        "topics_auto_added": topics_added,
    }


@router.get("", response_model=list[PaperOut])
def list_all(skip: int = 0, limit: int = 20):
    return list_papers(get_driver(), skip=skip, limit=limit)


@router.get("/{paper_id}", response_model=PaperOut)
def get_one(paper_id: str):
    paper = get_paper(get_driver(), paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    return paper


@router.patch("/{paper_id}", response_model=PaperOut)
def update(paper_id: str, body: PaperUpdate):
    data = {k: v for k, v in body.model_dump().items() if v is not None}
    paper = update_paper(get_driver(), paper_id, data)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    return paper


@router.delete("/{paper_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(paper_id: str):
    if not delete_paper(get_driver(), paper_id):
        raise HTTPException(status_code=404, detail="Paper not found")


@router.get("/{paper_id}/note", response_model=NoteOut)
def get_note(paper_id: str):
    note = get_paper_note(get_driver(), paper_id)
    if not note:
        raise HTTPException(status_code=404, detail="No note for this paper")
    return note


@router.post("/{paper_id}/chat", response_model=ChatResponse)
def chat(paper_id: str, body: ChatRequest):
    paper = get_paper(get_driver(), paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    raw_text = paper.get("raw_text") or ""
    history = [{"role": m.role, "content": m.content} for m in body.history]
    answer = chat_with_paper(
        paper_text=raw_text,
        paper_title=paper.get("title", ""),
        question=body.question,
        history=history,
    )
    return {"answer": answer}


@router.put("/{paper_id}/note", response_model=NoteOut)
def put_note(paper_id: str, body: NoteBody):
    if not get_paper(get_driver(), paper_id):
        raise HTTPException(status_code=404, detail="Paper not found")
    note = upsert_note(get_driver(), paper_id, body.content)
    mentions = parse_mentions(body.content)
    set_mentions(get_driver(), note["id"], mentions["people"], mentions["topics"])
    return note
