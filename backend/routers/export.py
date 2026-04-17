from fastapi import APIRouter, Depends
from fastapi.responses import Response
from neo4j import Driver

from db.connection import get_driver

router = APIRouter(prefix="/export", tags=["export"])


@router.get("/bibtex")
def export_bibtex(driver: Driver = Depends(get_driver)):
    """Export all papers as a BibTeX .bib file."""
    papers = []
    with driver.session() as session:
        result = session.run(
            """
            MATCH (p:Paper)
            OPTIONAL MATCH (p)<-[:AUTHORED_BY]-(person:Person)
            WITH p, collect(person.name) AS authors
            RETURN p, authors
            ORDER BY p.title
            """
        )
        for record in result:
            props = dict(record["p"])
            props["_authors"] = record["authors"]
            papers.append(props)

    lines: list[str] = []
    for p in papers:
        key = (p.get("id") or "unknown")[:8]
        title   = _bib_escape(p.get("title") or "")
        year    = p.get("year", "")
        doi     = p.get("doi") or ""
        authors = " and ".join(p.get("_authors") or [])

        lines.append(f"@article{{{key},")
        lines.append(f"  title  = {{{title}}},")
        if authors:
            lines.append(f"  author = {{{authors}}},")
        if year:
            lines.append(f"  year   = {{{year}}},")
        if doi:
            lines.append(f"  doi    = {{{doi}}},")
        lines.append("}")
        lines.append("")

    content = "\n".join(lines)
    return Response(
        content,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=papers.bib"},
    )


def _bib_escape(s: str) -> str:
    return s.replace("{", "\\{").replace("}", "\\}")
