"""
Discover router — unified search across arXiv, Semantic Scholar, and PubMed.
Allows users to search external sources and add papers in one click.
"""
from __future__ import annotations

import asyncio
import logging
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from db.connection import get_driver
from services.metadata_from_url import _get
from routers.papers import ingest_from_url as papers_ingest_from_url

log = logging.getLogger(__name__)
router = APIRouter(prefix="/discover", tags=["discover"])


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class SearchResult:
    title: str
    authors: list[str]
    year: int | None
    abstract: str | None
    doi: str | None
    url: str
    source: str  # "arxiv" | "semantic_scholar" | "pubmed"
    in_library: bool = False
    library_paper_id: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


# ── Search functions ──────────────────────────────────────────────────────────

def search_arxiv(query: str, limit: int = 20) -> list[SearchResult]:
    """Search arXiv by keyword."""
    if not query:
        return []

    results: list[SearchResult] = []
    r = _get(
        "https://export.arxiv.org/api/query",
        params={
            "search_query": f"all:{urllib.parse.quote(query)}",
            "max_results": limit,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        },
        timeout=30,
        retries=3,
        backoff=5.0,
    )
    if r is None:
        return []

    try:
        root = ET.fromstring(r.content)
    except ET.ParseError as e:
        log.warning("arXiv XML parse error: %s", e)
        return []

    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "arxiv": "http://arxiv.org/schemas/atom",
    }
    entries = root.findall(".//atom:entry", ns)

    for entry in entries:
        title_el = entry.find("atom:title", ns)
        abstract_el = entry.find("atom:summary", ns)
        published_el = entry.find("atom:published", ns)
        id_el = entry.find("atom:id", ns)

        if title_el is None or id_el is None:
            continue

        title = (title_el.text or "").strip().replace("\n", " ")
        abstract = (abstract_el.text or "").strip() if abstract_el is not None else None
        pub_date = (published_el.text or "")[:10] if published_el is not None else ""
        year = int(pub_date[:4]) if pub_date and len(pub_date) >= 4 else None

        id_url = id_el.text or ""
        arxiv_id = id_url.split("/")[-1]
        clean_id = arxiv_id.split("v")[0]

        # Authors
        authors = [
            (a.find("atom:name", ns).text or "").strip()
            for a in entry.findall("atom:author", ns)
            if a.find("atom:name", ns) is not None
        ]

        # DOI — prefer published DOI, fall back to arXiv DOI
        doi = None
        for link in entry.findall("atom:link", ns):
            if link.get("title") == "doi":
                doi = link.get("href", "").replace("https://doi.org/", "")
        if not doi:
            doi = f"arXiv:{clean_id}"

        results.append(SearchResult(
            title=title,
            abstract=abstract,
            authors=authors,
            doi=doi,
            year=year,
            url=f"https://arxiv.org/abs/{clean_id}",
            source="arxiv",
        ))

    return results[:limit]


def search_semantic_scholar(query: str, limit: int = 20) -> list[SearchResult]:
    """Search Semantic Scholar by keyword."""
    if not query:
        return []

    results: list[SearchResult] = []
    try:
        r = httpx.get(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            params={
                "query": query,
                "fields": "title,authors,year,abstract,externalIds,venue",
                "limit": limit,
            },
            timeout=15,
        )
        if r.status_code != 200:
            log.warning("S2 search failed: %d", r.status_code)
            return []

        data = r.json().get("data", [])
        for item in data:
            title = (item.get("title") or "").strip()
            if not title:
                continue

            authors = [
                a.get("name", "").strip()
                for a in item.get("authors", [])
                if a.get("name")
            ]
            year = item.get("year")
            abstract = (item.get("abstract") or "").strip() or None

            # DOI or arXiv ID
            ext_ids = item.get("externalIds") or {}
            doi = ext_ids.get("DOI")
            if not doi and ext_ids.get("ArXiv"):
                doi = f"arXiv:{ext_ids['ArXiv']}"

            paper_id = item.get("paperId") or ""
            url = f"https://www.semanticscholar.org/paper/{paper_id}" if paper_id else ""

            results.append(SearchResult(
                title=title,
                authors=authors,
                year=year,
                abstract=abstract,
                doi=doi,
                url=url,
                source="semantic_scholar",
            ))
    except Exception as e:
        log.warning("S2 search error: %s", e)

    return results[:limit]


def search_pubmed(query: str, limit: int = 20) -> list[SearchResult]:
    """Search PubMed by keyword."""
    if not query:
        return []

    _PUBMED_ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    _PUBMED_ESUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"

    # Step 1: esearch — get PMIDs
    r = _get(
        _PUBMED_ESEARCH,
        params={"db": "pubmed", "term": query, "retmax": limit, "retmode": "json"},
        timeout=20,
    )
    if r is None:
        return []

    try:
        pmids: list[str] = r.json().get("esearchresult", {}).get("idlist", [])
    except Exception as e:
        log.warning("PubMed esearch parse error: %s", e)
        return []

    if not pmids:
        return []

    # Step 2: esummary — get metadata
    results: list[SearchResult] = []
    r = _get(
        _PUBMED_ESUMMARY,
        params={"db": "pubmed", "id": ",".join(pmids), "retmode": "json"},
        timeout=30,
    )
    if r is None:
        return []

    try:
        data = r.json()
        result_dict = data.get("result", {})
        for pmid in pmids:
            if pmid not in result_dict:
                continue
            item = result_dict[pmid]

            title = (item.get("title") or "").strip()
            if not title:
                continue

            # Authors
            authors = []
            for a in item.get("authors", []):
                name = a.get("name", "").strip()
                if name:
                    authors.append(name)

            # Year
            pub_date = item.get("pubdate", "")
            year = None
            if pub_date:
                parts = pub_date.split()
                if parts and parts[0].isdigit():
                    year = int(parts[0])

            # DOI
            doi = None
            for aid in item.get("articleids", []):
                if aid.get("idtype") == "doi":
                    doi = aid.get("value")
                    break

            results.append(SearchResult(
                title=title,
                authors=authors,
                year=year,
                abstract=None,  # esummary doesn't provide abstracts
                doi=doi,
                url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                source="pubmed",
            ))
    except Exception as e:
        log.warning("PubMed esummary parse error: %s", e)

    return results[:limit]


def mark_in_library(results: list[SearchResult], driver) -> list[SearchResult]:
    """Mark which results are already in the library by DOI."""
    if not results:
        return results

    # Collect all DOIs
    dois = [r.doi for r in results if r.doi]
    if not dois:
        return results

    # Batch query
    with driver.session() as session:
        records = session.run(
            """
            UNWIND $dois AS d
            MATCH (p:Paper {doi: d})
            RETURN d AS doi, p.id AS id
            """,
            dois=dois,
        ).data()

    doi_map = {rec["doi"]: rec["id"] for rec in records}

    # Update results
    for r in results:
        if r.doi and r.doi in doi_map:
            r.in_library = True
            r.library_paper_id = doi_map[r.doi]

    return results


# ── API endpoints ─────────────────────────────────────────────────────────────

@router.get("/search")
async def discover_search(
    q: str = Query(..., description="Search query"),
    source: str = Query("all", description="Source filter: all|arxiv|s2|pubmed"),
    limit: int = Query(20, description="Max results per source"),
):
    """Search external sources for papers."""
    if not q or not q.strip():
        raise HTTPException(status_code=422, detail="Query cannot be empty")

    sources = []
    if source == "all":
        sources = ["arxiv", "s2", "pubmed"]
    elif source == "arxiv":
        sources = ["arxiv"]
    elif source == "s2":
        sources = ["s2"]
    elif source == "pubmed":
        sources = ["pubmed"]
    else:
        raise HTTPException(status_code=422, detail=f"Invalid source: {source}")

    # Run searches concurrently
    tasks = []
    if "arxiv" in sources:
        tasks.append(asyncio.to_thread(search_arxiv, q, limit))
    if "s2" in sources:
        tasks.append(asyncio.to_thread(search_semantic_scholar, q, limit))
    if "pubmed" in sources:
        tasks.append(asyncio.to_thread(search_pubmed, q, limit))

    results_lists = await asyncio.gather(*tasks, return_exceptions=True)

    # Combine results
    combined: list[SearchResult] = []
    for res_list in results_lists:
        if isinstance(res_list, Exception):
            log.warning("Search failed: %s", res_list)
            continue
        if isinstance(res_list, list):
            combined.extend(res_list)

    # Mark which are in library
    driver = get_driver()
    combined = await asyncio.to_thread(mark_in_library, combined, driver)

    return [r.to_dict() for r in combined]


class AddPaperBody(BaseModel):
    url: str
    project_id: str | None = None


@router.post("/add")
async def discover_add(body: AddPaperBody):
    """Add a paper from an external source URL."""
    # Delegate to the existing ingest endpoint
    return await papers_ingest_from_url(body.url, body.project_id, debug=False)
