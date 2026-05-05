"""
Author tracking router — track authors and auto-import their new papers.
"""
from __future__ import annotations

import logging
import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db.connection import get_driver
from db.queries.people import (
    set_person_tracked,
    list_tracked_people,
    get_person_library_dois,
    get_person,
    get_or_create_person_with_affiliation,
    link_author,
)
from db.queries.papers import merge_paper_by_doi
from db.queries.tags import tag_paper
from services.metadata_lookup import lookup_semantic_scholar

log = logging.getLogger(__name__)
router = APIRouter(tags=["author-tracker"])


# ── API models ────────────────────────────────────────────────────────────────

class TrackBody(BaseModel):
    tracked: bool


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.patch("/people/{person_id}/track")
def track_person(person_id: str, body: TrackBody):
    """Set tracked status for a person."""
    driver = get_driver()
    person = get_person(driver, person_id)
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")
    
    updated = set_person_tracked(driver, person_id, body.tracked)
    return updated


@router.get("/people/{person_id}/new-papers")
def get_person_new_papers(person_id: str, limit: int = 20):
    """Preview new papers by this person not yet in the library."""
    driver = get_driver()
    person = get_person(driver, person_id)
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")
    
    s2_author_id = person.get("s2_author_id")
    if not s2_author_id:
        return {"new_papers": [], "reason": "no_s2_author_id"}
    
    # Fetch papers from Semantic Scholar
    try:
        r = httpx.get(
            f"https://api.semanticscholar.org/graph/v1/author/{s2_author_id}/papers",
            params={
                "fields": "title,year,externalIds,abstract,venue,authors",
                "limit": limit,
            },
            timeout=15,
        )
        if r.status_code != 200:
            log.warning("S2 author papers fetch failed | author_id=%s | status=%d",
                       s2_author_id, r.status_code)
            return {"new_papers": [], "reason": "s2_api_error"}
        
        papers_data = r.json().get("data", [])
    except Exception as e:
        log.warning("S2 author papers fetch error | author_id=%s | %s", s2_author_id, e)
        return {"new_papers": [], "reason": "s2_api_error"}
    
    # Get DOIs already in library for this person
    known_dois = get_person_library_dois(driver, person_id)
    
    # Filter to new papers
    new_papers = []
    for paper in papers_data:
        ext_ids = paper.get("externalIds") or {}
        doi = ext_ids.get("DOI")
        if not doi and ext_ids.get("ArXiv"):
            doi = f"arXiv:{ext_ids['ArXiv']}"
        
        if not doi or doi in known_dois:
            continue
        
        # Format as SearchResult-like dict
        authors = [a.get("name", "") for a in paper.get("authors", []) if a.get("name")]
        url = f"https://doi.org/{doi}" if doi.startswith("10.") else f"https://arxiv.org/abs/{doi.replace('arXiv:', '')}"
        
        new_papers.append({
            "title": paper.get("title", ""),
            "authors": authors,
            "year": paper.get("year"),
            "abstract": paper.get("abstract"),
            "doi": doi,
            "url": url,
            "venue": paper.get("venue"),
            "in_library": False,
            "library_paper_id": None,
        })
    
    return {"new_papers": new_papers, "person_id": person_id}


@router.post("/author-tracker/check-all")
def check_tracked_authors():
    """
    Check all tracked authors and auto-import new papers.
    Returns summary of papers imported.
    """
    driver = get_driver()
    tracked = list_tracked_people(driver)
    
    total_imported = 0
    authors_checked = []
    
    for person in tracked:
        s2_author_id = person.get("s2_author_id")
        if not s2_author_id:
            authors_checked.append({
                "id": person["id"],
                "name": person["name"],
                "papers_imported": 0,
                "reason": "no_s2_author_id",
            })
            continue
        
        # Fetch recent papers from S2
        try:
            r = httpx.get(
                f"https://api.semanticscholar.org/graph/v1/author/{s2_author_id}/papers",
                params={
                    "fields": "title,year,externalIds,abstract,venue,authors,citationCount",
                    "limit": 20,
                },
                timeout=15,
            )
            if r.status_code != 200:
                authors_checked.append({
                    "id": person["id"],
                    "name": person["name"],
                    "papers_imported": 0,
                    "reason": "s2_api_error",
                })
                continue
            
            papers_data = r.json().get("data", [])
        except Exception as e:
            log.warning("S2 author papers fetch error | author_id=%s | %s", s2_author_id, e)
            authors_checked.append({
                "id": person["id"],
                "name": person["name"],
                "papers_imported": 0,
                "reason": "s2_api_error",
            })
            continue
        
        # Get DOIs already in library
        known_dois = get_person_library_dois(driver, person["id"])
        
        # Import new papers
        imported_count = 0
        for paper in papers_data:
            ext_ids = paper.get("externalIds") or {}
            doi = ext_ids.get("DOI")
            if not doi and ext_ids.get("ArXiv"):
                doi = f"arXiv:{ext_ids['ArXiv']}"
            
            if not doi or doi in known_dois:
                continue
            
            # Try to get more metadata from S2
            try:
                meta = lookup_semantic_scholar(doi)
                if not meta or not meta.get("title"):
                    continue
                
                # Create paper
                paper_node = merge_paper_by_doi(
                    driver,
                    doi=doi,
                    title=meta.get("title", ""),
                    year=meta.get("year"),
                    abstract=meta.get("abstract"),
                    venue=meta.get("venue"),
                    citation_count=meta.get("citation_count"),
                    metadata_source="semantic_scholar",
                )
                
                # Tag it
                tag_paper(driver, paper_node["id"], "from-author-tracker")
                
                # Link all authors
                authors_detail = meta.get("authors_detail") or []
                for author_data in authors_detail:
                    author_name = author_data.get("name")
                    if not author_name:
                        continue
                    author_person = get_or_create_person_with_affiliation(
                        driver,
                        author_name,
                        author_data.get("affiliation"),
                        author_data.get("s2_author_id"),
                    )
                    link_author(driver, paper_node["id"], author_person["id"])
                
                imported_count += 1
                total_imported += 1
            except Exception as e:
                log.warning("Failed to import paper | doi=%s | %s", doi, e)
                continue
        
        authors_checked.append({
            "id": person["id"],
            "name": person["name"],
            "papers_imported": imported_count,
        })
    
    return {
        "checked": len(tracked),
        "new_papers_imported": total_imported,
        "authors": authors_checked,
    }
