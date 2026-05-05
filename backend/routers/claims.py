"""Claims extraction and retrieval endpoints."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from db.connection import get_driver
from db.queries.claims import (
    create_claims,
    get_paper_claims,
    delete_paper_claims,
    search_claims,
)
from db.queries.papers import get_paper
from services.ai import extract_claims

log = logging.getLogger(__name__)
router = APIRouter(prefix="/", tags=["claims"])


class ClaimOut(BaseModel):
    id: str
    text: str
    type: str


class ClaimsOut(BaseModel):
    claims: list[ClaimOut]


class ExtractClaimsOut(BaseModel):
    claims: list[ClaimOut]
    count: int


class SearchClaimsOut(BaseModel):
    results: list[dict]


@router.get("/papers/{paper_id}/claims", response_model=ClaimsOut)
def get_claims(paper_id: str):
    """Get all claims for a paper."""
    driver = get_driver()
    claims = get_paper_claims(driver, paper_id)
    return ClaimsOut(
        claims=[
            ClaimOut(id=c["id"], text=c["text"], type=c["type"]) for c in claims
        ]
    )


@router.post("/papers/{paper_id}/claims/extract", response_model=ExtractClaimsOut)
def extract_paper_claims(paper_id: str, model: str | None = None):
    """Re-run claim extraction for a paper.
    
    Args:
        paper_id: The paper ID
        model: Optional model to use ('claude-haiku-4-5-20251001' or an Ollama model name).
               Defaults to Claude Haiku if not specified.
    """
    driver = get_driver()
    paper = get_paper(driver, paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    
    raw_text = paper.get("raw_text", "")
    if not raw_text or not raw_text.strip():
        raise HTTPException(
            status_code=422, detail="No raw text available for this paper"
        )
    
    # Delete existing claims
    delete_paper_claims(driver, paper_id)
    
    # Extract new claims with specified model
    claims_data = extract_claims(raw_text, paper.get("title", ""), model=model)
    
    if not claims_data:
        return ExtractClaimsOut(claims=[], count=0)
    
    # Save to database
    created = create_claims(driver, paper_id, claims_data)
    
    return ExtractClaimsOut(
        claims=[
            ClaimOut(id=c["id"], text=c["text"], type=c["type"]) for c in created
        ],
        count=len(created),
    )


@router.get("/claims/search", response_model=SearchClaimsOut)
def search_claims_endpoint(q: str, limit: int = 20):
    """Search claims across all papers."""
    driver = get_driver()
    results = search_claims(driver, q, limit)
    return SearchClaimsOut(results=results)
