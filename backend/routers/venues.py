import logging
from fastapi import APIRouter, HTTPException
from db.connection import get_driver
from models.schemas import VenueOut, PaperOut

log = logging.getLogger(__name__)

router = APIRouter(prefix="/venues", tags=["venues"])


@router.get("", response_model=list[VenueOut])
def list_venues(min_count: int = 1, q: str = ""):
    """
    List all venues in the library with paper counts and year ranges.
    
    Query parameters:
    - min_count: Minimum number of papers required (default: 1)
    - q: Filter venue names containing this string (case-insensitive)
    """
    driver = get_driver()
    
    with driver.session() as session:
        result = session.run(
            """
            MATCH (p:Paper)
            WHERE p.venue IS NOT NULL AND p.venue <> ""
            WITH p.venue AS name,
                 count(p) AS count,
                 collect(DISTINCT p.year) AS years
            WHERE count >= $min_count
            RETURN name, count, years
            ORDER BY count DESC
            """,
            min_count=min_count
        )
        
        venues = []
        for record in result:
            venue_name = record["name"]
            # Filter by query string if provided
            if q and q.lower() not in venue_name.lower():
                continue
            
            venues.append(VenueOut(
                name=venue_name,
                count=record["count"],
                years=[y for y in record["years"] if y is not None]
            ))
        
        return venues


@router.get("/{venue_name}/papers", response_model=list[PaperOut])
def get_venue_papers(venue_name: str):
    """
    Get all papers from a specific venue.
    
    Returns papers sorted by year (descending) and title.
    """
    driver = get_driver()
    
    with driver.session() as session:
        result = session.run(
            """
            MATCH (p:Paper {venue: $name})
            RETURN p.id AS id,
                   p.title AS title,
                   p.year AS year,
                   p.doi AS doi,
                   p.abstract AS abstract,
                   p.summary AS summary,
                   p.drive_file_id AS drive_file_id,
                   p.citation_count AS citation_count,
                   p.metadata_source AS metadata_source,
                   p.created_at AS created_at,
                   p.venue AS venue,
                   p.reading_status AS reading_status,
                   p.rating AS rating,
                   p.bookmarked AS bookmarked,
                   p.color AS color,
                   p.document_type AS document_type
            ORDER BY p.year DESC, p.title
            """,
            name=venue_name
        )
        
        papers = [dict(record) for record in result]
        
        if not papers:
            raise HTTPException(
                status_code=404,
                detail=f"No papers found for venue: {venue_name}"
            )
        
        return papers
