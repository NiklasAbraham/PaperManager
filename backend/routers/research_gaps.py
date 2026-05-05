import logging
from fastapi import APIRouter, HTTPException
from db.connection import get_driver
from db.queries.papers import get_paper
from db.queries.search import search_papers
from models.schemas import ResearchGapsRequest, ResearchGapsResponse
from services.ai import find_research_gaps

log = logging.getLogger(__name__)

router = APIRouter(prefix="/research-gaps", tags=["research-gaps"])


@router.post("", response_model=ResearchGapsResponse)
def analyze_research_gaps(body: ResearchGapsRequest):
    """
    Analyze research gaps for a given topic using the papers in the library.
    
    Uses Claude Opus with web search to identify:
    - What's covered well in the current library
    - Gaps in sub-topics or methodologies
    - Recommended papers to fill those gaps
    - Open research questions
    """
    driver = get_driver()
    papers = []
    
    # Logic to determine which papers to consider
    if body.paper_ids:
        # Option 1: Use specific paper IDs
        for paper_id in body.paper_ids:
            paper = get_paper(driver, paper_id)
            if paper:
                papers.append(paper)
    elif body.project_id:
        # Option 2: Use papers from a specific project
        with driver.session() as session:
            result = session.run(
                """
                MATCH (proj:Project {id: $project_id})-[:CONTAINS]->(p:Paper)
                RETURN p.id AS id, p.title AS title, p.abstract AS abstract, 
                       p.summary AS summary, p.year AS year
                ORDER BY p.year DESC, p.title
                """,
                project_id=body.project_id
            )
            papers = [dict(record) for record in result]
    else:
        # Option 3: Search library for papers related to topic (fulltext search)
        search_results = search_papers(
            driver,
            q=body.topic,
            limit=30,
        )
        papers = search_results.get("results", [])
    
    if not papers:
        raise HTTPException(
            status_code=404,
            detail="No papers found for analysis. Try adjusting your topic or scope."
        )
    
    # Extract relevant fields for AI analysis
    papers_for_ai = []
    for p in papers:
        papers_for_ai.append({
            "title": p.get("title", ""),
            "abstract": p.get("abstract", ""),
            "summary": p.get("summary", ""),
            "year": p.get("year"),
        })
    
    try:
        analysis = find_research_gaps(body.topic, papers_for_ai, body.model)
        return ResearchGapsResponse(
            analysis=analysis,
            papers_considered=len(papers),
            topic=body.topic
        )
    except Exception as exc:
        log.error("Research gap analysis failed | topic=%s | %s", body.topic, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Research gap analysis failed: {str(exc)}"
        )
