import logging
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, status
from fastapi.responses import Response
from typing import Optional

log = logging.getLogger(__name__)
from db.connection import get_driver
from db.queries.papers import create_paper, merge_paper_by_doi, get_paper, list_papers, update_paper, delete_paper
from db.queries.notes import get_paper_note, upsert_note, set_mentions
from db.queries.people import get_or_create_person, link_author
from db.queries.topics import get_or_create_topic, link_paper_topic
from db.queries.tags import tag_paper
from db.queries.projects import add_paper_to_project
from db.queries.references import create_or_link_reference, get_references, get_cited_by
from services.note_parser import parse_mentions
from services.pdf_parser import extract_metadata
from services.metadata_from_url import resolve_url
from services.drive import upload_pdf, get_file_url, delete_file, download_pdf
from services.ai import summarize_paper, chat_with_paper, chat_with_paper_work, chat_with_paper_ollama
from services.references import extract_references
from models.schemas import PaperCreate, PaperUpdate, PaperOut, NoteBody, NoteOut, IngestOut, IngestFromUrlBody, ChatRequest, ChatResponse, ReferencesBody

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
        log.info("Drive upload OK | file_id=%s | filename=%s", drive_file_id, filename)
    except Exception as exc:
        log.error("Drive upload failed | %s", exc)
        raise HTTPException(status_code=503, detail=f"Drive upload failed: {exc}")

    # Step 5: Summarize (best-effort — don't fail if Claude is down)
    summary = None
    try:
        summary = summarize_paper(raw_text, meta.get("title", ""))
        log.info("Summary generated | title=%.60s", meta.get("title"))
    except Exception as exc:
        log.warning("Summary failed (non-fatal) | %s", exc)

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

    log.info("Paper saved | id=%s | title=%.60s", paper["id"], paper.get("title"))

    # Step 6b: Apply source tag
    tag_paper(driver, paper["id"], "pdf-upload")

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

    # Step 10: Extract references (best-effort)
    references_found = []
    try:
        references_found = extract_references(raw_text, meta.get("doi"))
        log.info("References extracted | count=%d | paper_id=%s", len(references_found), paper["id"])
    except Exception as exc:
        log.warning("Reference extraction failed (non-fatal) | %s", exc)

    return {
        **paper,
        "drive_url": get_file_url(drive_file_id),
        "authors": authors_saved,
        "topics_auto_added": topics_added,
        "references_found": references_found,
    }


@router.post("/from-url", response_model=IngestOut, status_code=status.HTTP_201_CREATED)
def ingest_from_url(body: IngestFromUrlBody):
    """Ingest a paper from a URL (arXiv, DOI, PubMed, bioRxiv) — no PDF needed."""
    meta = resolve_url(body.url)
    if not meta or not meta.get("title"):
        raise HTTPException(status_code=422, detail="Could not resolve metadata from the given URL")

    log.info("Ingest from URL | url=%.80s | title=%.60s", body.url, meta.get("title"))

    # Summarize from abstract if available
    summary = None
    if meta.get("abstract"):
        try:
            summary = summarize_paper(meta["abstract"], meta.get("title", ""))
        except Exception as exc:
            log.warning("Summary failed (non-fatal) | %s", exc)

    driver = get_driver()
    # Use MERGE by DOI so that pulling a reference enriches the existing stub
    # instead of creating a duplicate node.
    paper = merge_paper_by_doi(driver, {
        "title": meta.get("title", ""),
        "year": meta.get("year"),
        "doi": meta.get("doi"),
        "abstract": meta.get("abstract"),
        "summary": summary,
        "drive_file_id": None,
        "citation_count": meta.get("citation_count"),
        "metadata_source": meta.get("metadata_source", "url"),
        "raw_text": "",
    })

    log.info("Paper saved from URL | id=%s | title=%.60s", paper["id"], paper.get("title"))

    # Apply source tag
    tag_paper(driver, paper["id"], "from-url")

    authors_saved = []
    for name in meta.get("authors", []):
        if not name:
            continue
        person = get_or_create_person(driver, name)
        link_author(driver, paper["id"], person["id"])
        authors_saved.append(name)

    topics_added = []
    for topic_name in meta.get("topics", []):
        if not topic_name:
            continue
        topic = get_or_create_topic(driver, topic_name)
        link_paper_topic(driver, paper["id"], topic["id"])
        topics_added.append(topic_name)

    if body.project_id:
        try:
            add_paper_to_project(driver, body.project_id, paper["id"])
        except Exception:
            pass

    return {
        **paper,
        "drive_url": None,
        "authors": authors_saved,
        "topics_auto_added": topics_added,
        "references_found": [],
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
    data = {k: v for k, v in body.model_dump().items() if k in body.model_fields_set}
    paper = update_paper(get_driver(), paper_id, data)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    return paper


@router.delete("/{paper_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(paper_id: str):
    paper = get_paper(get_driver(), paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    # Remove from Google Drive (best-effort)
    if paper.get("drive_file_id"):
        try:
            delete_file(paper["drive_file_id"])
            log.info("Drive file deleted | file_id=%s", paper["drive_file_id"])
        except Exception as exc:
            log.warning("Drive delete failed (non-fatal) | %s", exc)
    delete_paper(get_driver(), paper_id)
    log.info("Paper deleted | id=%s | title=%.60s", paper_id, paper.get("title"))


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
    kwargs = dict(paper_text=raw_text, paper_title=paper.get("title", ""), question=body.question, history=history)
    if body.model == "ollama":
        answer = chat_with_paper_ollama(**kwargs)
    elif body.model == "claude-work":
        answer = chat_with_paper_work(**kwargs)
    else:
        answer = chat_with_paper(**kwargs)
    return {"answer": answer}


@router.put("/{paper_id}/note", response_model=NoteOut)
def put_note(paper_id: str, body: NoteBody):
    if not get_paper(get_driver(), paper_id):
        raise HTTPException(status_code=404, detail="Paper not found")
    note = upsert_note(get_driver(), paper_id, body.content)
    mentions = parse_mentions(body.content)
    set_mentions(get_driver(), note["id"], mentions["people"], mentions["topics"])
    return note


# ── Reference endpoints ────────────────────────────────────────────────────────

@router.get("/{paper_id}/extract-references")
def extract_refs(paper_id: str):
    """Run reference extraction on the stored raw_text (on-demand, no saving)."""
    paper = get_paper(get_driver(), paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    raw_text = paper.get("raw_text") or ""
    doi = paper.get("doi")
    refs = extract_references(raw_text, doi)
    return {"references": refs}


@router.post("/{paper_id}/references", status_code=status.HTTP_201_CREATED)
def save_references(paper_id: str, body: ReferencesBody):
    """Save a confirmed list of references as CITES relationships."""
    if not get_paper(get_driver(), paper_id):
        raise HTTPException(status_code=404, detail="Paper not found")
    driver = get_driver()
    saved = []
    for ref in body.references:
        node = create_or_link_reference(driver, paper_id, ref)
        if node:
            tag_paper(driver, node["id"], "from-references")
            saved.append(node)
    return {"saved": len(saved)}


@router.get("/{paper_id}/references")
def list_references(paper_id: str):
    """Return CITES outgoing (references) and incoming (cited-by) lists."""
    if not get_paper(get_driver(), paper_id):
        raise HTTPException(status_code=404, detail="Paper not found")
    driver = get_driver()
    return {
        "references": get_references(driver, paper_id),
        "cited_by":   get_cited_by(driver, paper_id),
    }


@router.get("/{paper_id}/pdf")
def stream_pdf(paper_id: str):
    """Proxy the PDF from Google Drive so the browser can render it without third-party cookies."""
    paper = get_paper(get_driver(), paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    file_id = paper.get("drive_file_id")
    if not file_id:
        raise HTTPException(status_code=404, detail="No PDF stored for this paper")
    try:
        pdf_bytes = download_pdf(file_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Drive download failed: {exc}")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "inline"},
    )
