from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status
from db.connection import get_driver
from db.queries.people import (
    create_person, get_person, list_people, list_people_without_tag, delete_person,
    link_author, link_involves, link_specializes,
    unlink_author, unlink_involves,
    get_papers_by_person, get_specialties, get_involves_for_paper, get_authors_for_paper,
)
from db.queries.notes import get_person_note, upsert_person_note, set_mentions
from db.queries.tags import tag_person, untag_person, get_tags_for_person, get_or_create_tag
from services.note_parser import parse_mentions
from services.person_enrichment import enrich_person_by_id, enrich_all_people, enrich_person_from_papers_ollama
from models.schemas import (
    PersonCreate, PersonUpdate, PersonOut, AuthorLink, InvolvesLink, SpecialtyLink,
    NoteBody, NoteOut, TagBody, PersonEnrichOut,
)
from db.queries.topics import get_or_create_topic

router = APIRouter(tags=["people"])
people_router = APIRouter(prefix="/people", tags=["people"])
papers_router = APIRouter(prefix="/papers", tags=["people"])

DEFAULT_PEOPLE_TAGS = [
    "known-personally",
    "collaborator", "recruiter", "advisor", "mentor", "investor",
    "tech-lead", "co-founder", "hiring-manager", "contact",
    "met-at-conference", "follow-up", "strong-reference", "potential-hire",
    "phd-student", "postdoc", "professor", "industry", "academia",
]

KNOWN_PERSONALLY_TAG = "known-personally"


def seed_people_tags(driver):
    for name in DEFAULT_PEOPLE_TAGS:
        get_or_create_tag(driver, name)


# ── CRUD ──────────────────────────────────────────────────────────────────────

@people_router.post("", response_model=PersonOut, status_code=status.HTTP_201_CREATED)
def create(body: PersonCreate):
    driver = get_driver()
    person = create_person(driver, body.model_dump())
    # Auto-tag manually added people as "known-personally"
    tag_person(driver, person["id"], KNOWN_PERSONALLY_TAG)
    return person


@people_router.post("/get-or-create", response_model=PersonOut)
def get_or_create(body: PersonCreate):
    """Return existing person matched by name (case-insensitive) or create a new one."""
    from db.queries.people import get_or_create_person
    return get_or_create_person(get_driver(), body.name)


@people_router.get("", response_model=list[PersonOut])
def list_all(tag: str | None = Query(None), exclude_tag: str | None = Query(None)):
    driver = get_driver()
    if tag:
        return list_people(driver, tag=tag)
    if exclude_tag:
        return list_people_without_tag(driver, tag=exclude_tag)
    return list_people(driver)


@people_router.get("/{person_id}")
def get_one(person_id: str):
    person = get_person(get_driver(), person_id)
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")
    papers = get_papers_by_person(get_driver(), person_id)
    specialties = get_specialties(get_driver(), person_id)
    tags = get_tags_for_person(get_driver(), person_id)
    note = get_person_note(get_driver(), person_id)
    return {**person, "papers": papers, "specialties": specialties, "tags": tags, "note": note}


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


# ── Notes ──────────────────────────────────────────────────────────────────────

@people_router.get("/{person_id}/note", response_model=NoteOut)
def get_note(person_id: str):
    if not get_person(get_driver(), person_id):
        raise HTTPException(status_code=404, detail="Person not found")
    note = get_person_note(get_driver(), person_id)
    if not note:
        raise HTTPException(status_code=404, detail="No note yet")
    return note


@people_router.put("/{person_id}/note", response_model=NoteOut)
def upsert_note(person_id: str, body: NoteBody):
    if not get_person(get_driver(), person_id):
        raise HTTPException(status_code=404, detail="Person not found")
    note = upsert_person_note(get_driver(), person_id, body.content)
    mentions = parse_mentions(body.content)
    set_mentions(get_driver(), note["id"], mentions["people"], mentions["topics"])
    return note


# ── Tags ───────────────────────────────────────────────────────────────────────

@people_router.get("/{person_id}/tags")
def list_tags(person_id: str):
    if not get_person(get_driver(), person_id):
        raise HTTPException(status_code=404, detail="Person not found")
    return get_tags_for_person(get_driver(), person_id)


@people_router.post("/{person_id}/tags", status_code=status.HTTP_201_CREATED)
def add_tag(person_id: str, body: TagBody):
    if not get_person(get_driver(), person_id):
        raise HTTPException(status_code=404, detail="Person not found")
    return tag_person(get_driver(), person_id, body.name)


@people_router.delete("/{person_id}/tags/{tag_name}", status_code=status.HTTP_204_NO_CONTENT)
def remove_tag(person_id: str, tag_name: str):
    untag_person(get_driver(), person_id, tag_name)


# ── Enrichment ────────────────────────────────────────────────────────────────

@people_router.post("/{person_id}/enrich", response_model=PersonEnrichOut)
def enrich_one(person_id: str):
    """Re-run ORCID/Scholar/S2 + Ollama paper-scan enrichment for a single person."""
    return enrich_person_by_id(get_driver(), person_id)


@people_router.post("/{person_id}/enrich-papers")
def enrich_from_papers(person_id: str):
    """Use Ollama to extract profile info (affiliation, bio, skills) from connected paper texts."""
    if not get_person(get_driver(), person_id):
        raise HTTPException(status_code=404, detail="Person not found")
    updated = enrich_person_from_papers_ollama(get_driver(), person_id)
    return {"person_id": person_id, "fields_updated": list(updated.keys()), "data": updated}


@people_router.post("/enrich-all")
def enrich_all(background_tasks: BackgroundTasks):
    """Kick off background enrichment for people who have little/no profile data."""
    from services.person_enrichment import _is_empty_profile
    from db.queries.people import get_person as _get_person
    driver = get_driver()
    with driver.session() as session:
        result = session.run(
            "MATCH (p:Person) WHERE ()-[:AUTHORED_BY|INVOLVES]->(p) RETURN p.id AS id"
        )
        all_ids = [r["id"] for r in result]
    # Count only those who actually need enrichment
    needs_enrich = sum(
        1 for pid in all_ids
        if (p := _get_person(driver, pid)) and _is_empty_profile(p)
    )
    background_tasks.add_task(enrich_all_people, driver)
    return {"status": "started", "total_people": needs_enrich}


# ── Paper ↔ Person relationships ──────────────────────────────────────────────

@papers_router.get("/{paper_id}/authors")
def list_authors(paper_id: str):
    return get_authors_for_paper(get_driver(), paper_id)


@papers_router.post("/{paper_id}/authors", status_code=status.HTTP_201_CREATED)
def add_author(paper_id: str, body: AuthorLink):
    link_author(get_driver(), paper_id, body.person_id)
    return {"paper_id": paper_id, "person_id": body.person_id, "rel": "AUTHORED_BY"}


@papers_router.get("/{paper_id}/involves")
def list_involves(paper_id: str):
    return get_involves_for_paper(get_driver(), paper_id)


@papers_router.post("/{paper_id}/involves", status_code=status.HTTP_201_CREATED)
def add_involves(paper_id: str, body: InvolvesLink):
    link_involves(get_driver(), paper_id, body.person_id, body.role)
    return {"paper_id": paper_id, "person_id": body.person_id, "role": body.role}


@papers_router.post("/{paper_id}/ai-extract-authors")
def ai_extract_authors(paper_id: str):
    """Use Claude Work (→ personal → Ollama) to extract full author info from the first page."""
    import json as _json
    import anthropic as _anthropic
    import httpx as _httpx
    import logging as _logging
    from config import settings as _settings
    from db.queries.papers import get_paper
    from db.queries.people import get_or_create_person_with_affiliation, update_person_props

    _log = _logging.getLogger(__name__)
    driver = get_driver()
    paper = get_paper(driver, paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    raw_text = paper.get("raw_text") or ""
    if not raw_text.strip():
        raise HTTPException(status_code=422, detail="No extracted text stored for this paper — upload the PDF first")

    # Use a generous first-page slice — author blocks are almost always in the first ~8 000 chars
    snippet = raw_text[:8000]
    prompt = (
        "Extract all authors from this academic paper's first page.\n"
        "For each author, extract as much of the following as is present in the text:\n"
        "  name (required), affiliation, email, orcid_url, website_url\n"
        "Return ONLY valid JSON: {\"authors\": [{...}, ...]}\n"
        "Each object must have at least \"name\". Other fields are optional — omit or set null if not found.\n"
        "Include only actual human authors, not editors, funding bodies, or journal names.\n\n"
        f"Paper text:\n{snippet}"
    )

    def _parse_llm_json(raw: str) -> dict:
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return _json.loads(raw.strip())

    result: dict | None = None

    # 1. Claude Work (primary)
    if _settings.anthropic_work_api_key:
        try:
            kwargs: dict = {"api_key": _settings.anthropic_work_api_key, "http_client": _httpx.Client(verify=False)}
            if _settings.anthropic_work_base_url:
                kwargs["base_url"] = _settings.anthropic_work_base_url
            client = _anthropic.Anthropic(**kwargs)
            resp = client.messages.create(
                model="claude-sonnet-4-6", max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            result = _parse_llm_json(resp.content[0].text)
        except Exception as exc:
            _log.debug("Claude Work ai-extract-authors failed: %s", exc)

    # 2. Claude personal
    if result is None and _settings.anthropic_api_key:
        try:
            client = _anthropic.Anthropic(api_key=_settings.anthropic_api_key)
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001", max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            result = _parse_llm_json(resp.content[0].text)
        except Exception as exc:
            _log.debug("Claude personal ai-extract-authors failed: %s", exc)

    # 3. Ollama fallback
    if result is None:
        try:
            import ollama as _ollama
            resp = _ollama.chat(
                model=_settings.ollama_model,
                messages=[{"role": "user", "content": prompt}],
                format="json",
            )
            result = _parse_llm_json(resp["message"]["content"])
        except Exception as exc:
            _log.debug("Ollama ai-extract-authors failed: %s", exc)

    if result is None:
        raise HTTPException(status_code=503, detail="All LLM backends failed")

    _ALLOWED_EXTRA = {"email", "orcid_url", "website_url"}
    added = []
    for entry in result.get("authors", []):
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        affiliation = str(entry.get("affiliation") or "").strip() or None
        person = get_or_create_person_with_affiliation(driver, name, affiliation)
        # Enrich with any extra fields the LLM found, skipping already-set values
        extras = {k: str(v).strip() for k, v in entry.items() if k in _ALLOWED_EXTRA and v and str(v).strip()}
        if extras:
            # Only set fields that aren't already populated on the node
            to_set = {k: v for k, v in extras.items() if not person.get(k)}
            if to_set:
                updated = update_person_props(driver, person["id"], to_set)
                if updated:
                    person = updated
        link_author(driver, paper_id, person["id"])
        added.append(person)

    return {"authors": added}


@papers_router.delete("/{paper_id}/authors/{person_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_author(paper_id: str, person_id: str):
    unlink_author(get_driver(), paper_id, person_id)


@papers_router.delete("/{paper_id}/involves/{person_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_involves(paper_id: str, person_id: str, role: str | None = Query(None)):
    unlink_involves(get_driver(), paper_id, person_id, role)
