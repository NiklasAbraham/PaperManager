"""Cross-paper synthesis endpoints."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db.connection import get_driver
from db.queries.papers import get_paper
from services.ai import synthesize_papers

log = logging.getLogger(__name__)
router = APIRouter(prefix="/synthesis", tags=["synthesis"])


class SynthesisRequest(BaseModel):
    paper_ids: list[str]
    question: str
    use_web: bool = True


class SynthesisResponse(BaseModel):
    synthesis: str
    papers_used: list[dict]


@router.post("", response_model=SynthesisResponse)
def synthesize(body: SynthesisRequest):
    """Synthesize insights across 2-10 papers."""
    driver = get_driver()
    
    # Validate count
    if len(body.paper_ids) < 2:
        raise HTTPException(status_code=422, detail="Need at least 2 papers for synthesis")
    if len(body.paper_ids) > 10:
        raise HTTPException(status_code=422, detail="Cannot synthesize more than 10 papers at once")
    
    # Load papers
    papers = []
    for paper_id in body.paper_ids:
        paper = get_paper(driver, paper_id)
        if not paper:
            raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found")
        papers.append(paper)
    
    # Generate synthesis
    synthesis = synthesize_papers(papers, body.question, body.use_web)
    
    # Return synthesis + metadata
    papers_used = [
        {"id": p["id"], "title": p.get("title", "Untitled")}
        for p in papers
    ]
    
    return SynthesisResponse(synthesis=synthesis, papers_used=papers_used)
