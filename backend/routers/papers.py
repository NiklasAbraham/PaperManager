import logging
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, status
from fastapi.responses import Response
from typing import Optional

log = logging.getLogger(__name__)
from db.connection import get_driver
from db.queries.papers import create_paper, merge_paper_by_doi, get_paper, list_papers, update_paper, delete_paper, find_duplicate, random_paper
from db.queries.notes import get_paper_note, upsert_note, set_mentions
from db.queries.people import get_or_create_person, get_or_create_person_with_affiliation, link_author
from db.queries.topics import get_or_create_topic, link_paper_topic
from db.queries.tags import tag_paper
from db.queries.projects import add_paper_to_project
from db.queries.references import create_or_link_reference, get_references, get_cited_by
from db.queries.figures import list_figures, delete_figures_for_paper
from services.note_parser import parse_mentions
from services.pdf_parser import extract_metadata
from services.metadata_from_url import resolve_url
from services.drive import upload_pdf, get_file_url, delete_file, download_pdf
from services.ai import summarize_paper, suggest_topics, chat_with_paper, chat_with_paper_work, chat_with_paper_ollama, extract_affiliations_with_ollama
from services.references import extract_references
from services.figure_extractor import extract_figures
from services.drive import upload_image
from db.queries.figures import create_figure
from models.schemas import PaperCreate, PaperUpdate, PaperOut, NoteBody, NoteOut, IngestOut, IngestFromUrlBody, ChatRequest, ChatResponse, ReferencesBody

router = APIRouter(prefix="/papers", tags=["papers"])


@router.get("/check-duplicate")
def check_duplicate(doi: Optional[str] = None, title: Optional[str] = None):
    """Return {duplicate: paper | null} — used by the frontend before confirming upload."""
    if not doi and not title:
        return {"duplicate": None}
    existing = find_duplicate(get_driver(), doi=doi or None, title=title or None)
    if existing:
        existing.pop("raw_text", None)
        return {"duplicate": existing}
    return {"duplicate": None}


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
    caption_method: Optional[str] = Form("ollama"),
    summary_instructions: Optional[str] = Form(None),
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
        summary = summarize_paper(raw_text, meta.get("title", ""), custom_instructions=summary_instructions or None)
        log.info("Summary generated | title=%.60s", meta.get("title"))
    except Exception as exc:
        log.warning("Summary failed (non-fatal) | %s", exc)

    # Step 6: Save paper to Neo4j — deduplicate by DOI then by title
    driver = get_driver()
    import json as _json

    existing = find_duplicate(driver, doi=meta.get("doi"), title=meta.get("title", ""))
    if existing:
        if existing.get("drive_file_id"):
            # Full paper already in library — block duplicate
            raise HTTPException(
                status_code=409,
                detail=_json.dumps({
                    "message": "Paper already exists in your library",
                    "existing_id": existing["id"],
                    "existing_title": existing.get("title", ""),
                }),
            )
        # Stub (no PDF yet) — enrich it with the new upload data
        log.info("Enriching stub paper %s with uploaded PDF", existing["id"])
        paper = merge_paper_by_doi(driver, {
            "title": meta.get("title", ""),
            "year": meta.get("year"),
            "doi": meta.get("doi") or existing.get("doi"),
            "abstract": meta.get("abstract"),
            "summary": summary,
            "drive_file_id": drive_file_id,
            "citation_count": meta.get("citation_count"),
            "metadata_source": meta.get("metadata_source", "heuristic"),
            "raw_text": raw_text,
            "venue": meta.get("venue"),
        }) if meta.get("doi") or existing.get("doi") else create_paper(driver, {
            "title": meta.get("title", ""),
            "year": meta.get("year"),
            "doi": meta.get("doi"),
            "abstract": meta.get("abstract"),
            "summary": summary,
            "drive_file_id": drive_file_id,
            "citation_count": meta.get("citation_count"),
            "metadata_source": meta.get("metadata_source", "heuristic"),
            "raw_text": raw_text,
            "venue": meta.get("venue"),
        })
    elif meta.get("doi"):
        # No existing paper but DOI known — use merge to future-proof against race conditions
        paper = merge_paper_by_doi(driver, {
            "title": meta.get("title", ""),
            "year": meta.get("year"),
            "doi": meta.get("doi"),
            "abstract": meta.get("abstract"),
            "summary": summary,
            "drive_file_id": drive_file_id,
            "citation_count": meta.get("citation_count"),
            "metadata_source": meta.get("metadata_source", "heuristic"),
            "raw_text": raw_text,
            "venue": meta.get("venue"),
        })
    else:
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
            "venue": meta.get("venue"),
        })

    log.info("Paper saved | id=%s | title=%.60s", paper["id"], paper.get("title"))

    # Step 6b: Apply source tag
    tag_paper(driver, paper["id"], "pdf-upload")

    # Step 7: Link authors (with affiliations)
    authors_detail = meta.get("authors_detail") or []
    aff_map = {d["name"]: d.get("affiliation") for d in authors_detail}

    # Ollama fallback for any author still missing an affiliation
    missing = [n for n in meta.get("authors", []) if n and not aff_map.get(n)]
    if missing and raw_text:
        try:
            ollama_affs = extract_affiliations_with_ollama(missing, raw_text)
            aff_map.update(ollama_affs)
            log.info("Ollama affiliations extracted | count=%d", len(ollama_affs))
        except Exception as exc:
            log.warning("Ollama affiliation extraction failed (non-fatal) | %s", exc)

    authors_saved = []
    for name in meta.get("authors", []):
        if not name:
            continue
        person = get_or_create_person_with_affiliation(driver, name, aff_map.get(name))
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

    # Step 8b: AI topic suggestion (best-effort, supplements Semantic Scholar topics)
    try:
        ai_topics = suggest_topics(
            title=meta.get("title", ""),
            abstract=meta.get("abstract", "") or "",
            summary=summary or "",
        )
        for topic_name in ai_topics:
            if topic_name and topic_name not in topics_added:
                link_paper_topic(driver, paper["id"], topic_name)
                topics_added.append(topic_name)
        log.info("AI topics added | count=%d | paper_id=%s", len(ai_topics), paper["id"])
    except Exception as exc:
        log.warning("AI topic suggestion failed (non-fatal) | %s", exc)

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

    # Step 11: Extract figures (best-effort)
    try:
        figs = extract_figures(pdf_bytes, caption_method=caption_method or "ollama")
        for i, fig in enumerate(figs):
            fig_filename = f"{paper['id']}_p{fig['page_number']}_{i+1}.png"
            fig_drive_id = upload_image(fig["image_bytes"], fig_filename)
            create_figure(driver, {
                "paper_id": paper["id"],
                "figure_number": fig["figure_number"],
                "caption": fig["caption"],
                "drive_file_id": fig_drive_id,
                "page_number": fig["page_number"],
            })
        log.info("Figures extracted | count=%d | paper_id=%s", len(figs), paper["id"])
    except Exception as exc:
        log.warning("Figure extraction failed (non-fatal) | %s", exc)

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
        "venue": meta.get("venue"),
    })

    log.info("Paper saved from URL | id=%s | title=%.60s", paper["id"], paper.get("title"))

    # Apply source tag
    tag_paper(driver, paper["id"], "from-url")

    authors_detail = meta.get("authors_detail") or []
    aff_map = {d["name"]: d.get("affiliation") for d in authors_detail}

    authors_saved = []
    for name in meta.get("authors", []):
        if not name:
            continue
        person = get_or_create_person_with_affiliation(driver, name, aff_map.get(name))
        link_author(driver, paper["id"], person["id"])
        authors_saved.append(name)

    topics_added = []
    for topic_name in meta.get("topics", []):
        if not topic_name:
            continue
        topic = get_or_create_topic(driver, topic_name)
        link_paper_topic(driver, paper["id"], topic["id"])
        topics_added.append(topic_name)

    # AI topic suggestion (best-effort)
    try:
        ai_topics = suggest_topics(
            title=meta.get("title", ""),
            abstract=meta.get("abstract", "") or "",
            summary=summary or "",
        )
        for topic_name in ai_topics:
            if topic_name and topic_name not in topics_added:
                link_paper_topic(driver, paper["id"], topic_name)
                topics_added.append(topic_name)
    except Exception as exc:
        log.warning("AI topic suggestion failed (non-fatal) | %s", exc)

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


@router.get("/random", response_model=PaperOut)
def get_random_paper(reading_status: Optional[str] = None):
    """Return a random paper from the library, optionally filtered by reading_status."""
    paper = random_paper(get_driver(), reading_status=reading_status or None)
    if not paper:
        raise HTTPException(status_code=404, detail="No papers found")
    return paper


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
    driver = get_driver()
    paper = get_paper(driver, paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    # Delete figure images from Drive, then figure nodes from Neo4j
    figs = list_figures(driver, paper_id)
    for fig in figs:
        if fig.get("drive_file_id"):
            try:
                delete_file(fig["drive_file_id"])
            except Exception as exc:
                log.warning("Figure Drive delete failed (non-fatal) | %s", exc)
    if figs:
        delete_figures_for_paper(driver, paper_id)
        log.info("Figures deleted | count=%d | paper_id=%s", len(figs), paper_id)

    # Delete the note attached to this paper
    with driver.session() as session:
        session.run(
            "MATCH (n:Note)-[:ABOUT]->(p:Paper {id: $id}) DETACH DELETE n",
            id=paper_id,
        )

    # Delete PDF from Drive (best-effort)
    if paper.get("drive_file_id"):
        try:
            delete_file(paper["drive_file_id"])
            log.info("Drive file deleted | file_id=%s", paper["drive_file_id"])
        except Exception as exc:
            log.warning("Drive delete failed (non-fatal) | %s", exc)

    delete_paper(driver, paper_id)
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


@router.get("/{paper_id}/bibtex")
def paper_bibtex(paper_id: str):
    """Return a BibTeX entry for a single paper."""
    paper = get_paper(get_driver(), paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    driver = get_driver()
    with driver.session() as session:
        result = session.run(
            "MATCH (p:Paper {id: $id})<-[:AUTHORED_BY]-(a:Person) RETURN collect(a.name) AS authors",
            id=paper_id,
        )
        record = result.single()
        authors = record["authors"] if record else []

    key = paper_id[:8]
    title = _bib_escape(paper.get("title") or "")
    year = paper.get("year", "")
    doi = paper.get("doi") or ""
    venue = paper.get("venue") or ""
    author_str = " and ".join(authors)

    lines = [f"@article{{{key},"]
    lines.append(f"  title  = {{{title}}},")
    if author_str:
        lines.append(f"  author = {{{author_str}}},")
    if year:
        lines.append(f"  year   = {{{year}}},")
    if doi:
        lines.append(f"  doi    = {{{doi}}},")
    if venue:
        lines.append(f"  journal = {{{_bib_escape(venue)}}},")
    lines.append("}")

    content = "\n".join(lines) + "\n"
    filename = f"{_safe_filename(paper.get('title') or key)}.bib"
    return Response(
        content,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=\"{filename}\""},
    )


def _bib_escape(s: str) -> str:
    return s.replace("{", "\\{").replace("}", "\\}")


def _safe_filename(title: str, max_len: int = 40) -> str:
    """Return a filesystem-safe version of *title*, stripped to *max_len* chars."""
    return "".join(c for c in title[:max_len] if c.isalnum() or c in " _-").strip()
