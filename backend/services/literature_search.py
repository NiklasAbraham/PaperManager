"""
Search arXiv, PubMed, and bioRxiv by date range and keyword.

Keywords are loaded from prompts/literature_search_keywords.txt (one per line,
# lines ignored). No papers are saved — callers receive plain dicts for display.
"""

from __future__ import annotations

import logging
import time
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, asdict
from datetime import date, timedelta
from pathlib import Path

from neo4j import Driver

from db.queries.papers import find_duplicate
from services.metadata_from_url import _get  # reuse retry helper + UA

log = logging.getLogger(__name__)

_KEYWORDS_FILE = Path(__file__).parent.parent.parent / "prompts" / "literature_search_keywords.txt"


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class LitPaper:
    title: str
    abstract: str | None
    authors: list[str]
    doi: str | None
    year: int | None
    date: str               # ISO YYYY-MM-DD
    source: str             # "arxiv" | "pubmed" | "biorxiv"
    url: str                # canonical URL usable by existing ingestFromUrl()
    already_in_library: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


# ── Keyword loading ────────────────────────────────────────────────────────────

def load_keywords() -> list[str]:
    """Read keywords from prompt file. Returns list of non-empty, non-comment strings."""
    try:
        lines = _KEYWORDS_FILE.read_text(encoding="utf-8").splitlines()
        return [l.strip() for l in lines if l.strip() and not l.strip().startswith("#")]
    except FileNotFoundError:
        log.warning("literature_search_keywords.txt not found — using empty keyword list")
        return []


# ── arXiv ─────────────────────────────────────────────────────────────────────

def search_arxiv(keywords: list[str], start: date, end: date, max_results: int = 100) -> list[LitPaper]:
    """Search arXiv by title keyword(s) and date range."""
    if not keywords:
        return []

    # Build query: (ti:protein OR ti:peptide OR ...) AND submittedDate:[from TO to]
    ti_terms = " OR ".join(f"ti:{urllib.parse.quote(kw)}" for kw in keywords)
    date_from = start.strftime("%Y%m%d") + "000000"
    date_to   = end.strftime("%Y%m%d")   + "235959"
    query = f"({ti_terms}) AND submittedDate:[{date_from} TO {date_to}]"

    results: list[LitPaper] = []
    start_idx = 0
    batch = 100

    while len(results) < max_results:
        fetch = min(batch, max_results - len(results))
        r = _get(
            "http://export.arxiv.org/api/query",
            params={
                "search_query": query,
                "start": start_idx,
                "max_results": fetch,
                "sortBy": "submittedDate",
                "sortOrder": "descending",
            },
            timeout=30,
            retries=3,
            backoff=5.0,
        )
        if r is None:
            break

        try:
            root = ET.fromstring(r.content)
        except ET.ParseError as e:
            log.warning("arXiv XML parse error: %s", e)
            break

        ns = {
            "atom":   "http://www.w3.org/2005/Atom",
            "arxiv":  "http://arxiv.org/schemas/atom",
        }
        entries = root.findall(".//atom:entry", ns)
        if not entries:
            break

        for entry in entries:
            title_el    = entry.find("atom:title", ns)
            abstract_el = entry.find("atom:summary", ns)
            published_el = entry.find("atom:published", ns)
            id_el       = entry.find("atom:id", ns)

            if title_el is None or id_el is None:
                continue

            title    = (title_el.text or "").strip().replace("\n", " ")
            abstract = (abstract_el.text or "").strip() if abstract_el is not None else None
            pub_date = (published_el.text or "")[:10] if published_el is not None else ""
            year     = int(pub_date[:4]) if pub_date else None

            id_url   = id_el.text or ""
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

            results.append(LitPaper(
                title=title,
                abstract=abstract,
                authors=authors,
                doi=doi,
                year=year,
                date=pub_date,
                source="arxiv",
                url=f"https://arxiv.org/abs/{clean_id}",
            ))

        start_idx += len(entries)
        if len(entries) < fetch:
            break  # No more results
        time.sleep(3)  # Respect arXiv rate limit

    return results[:max_results]


# ── PubMed ────────────────────────────────────────────────────────────────────

_PUBMED_ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
_PUBMED_EFETCH  = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


def search_pubmed(keywords: list[str], start: date, end: date, max_results: int = 100) -> list[LitPaper]:
    """Search PubMed by keyword and date range using raw eUtils HTTP (no biopython)."""
    if not keywords:
        return []

    terms = " OR ".join(f'"{kw}"[Title/Abstract]' for kw in keywords)
    date_range = f"{start.strftime('%Y/%m/%d')}:{end.strftime('%Y/%m/%d')}[Date - Publication]"
    query = f"({terms}) AND {date_range}"

    # Step 1: esearch — get PMIDs
    r = _get(
        _PUBMED_ESEARCH,
        params={"db": "pubmed", "term": query, "retmax": max_results, "retmode": "json"},
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

    # Step 2: efetch in batches — get full records as XML
    results: list[LitPaper] = []
    batch_size = 50
    for i in range(0, len(pmids), batch_size):
        batch = pmids[i:i + batch_size]
        r = _get(
            _PUBMED_EFETCH,
            params={"db": "pubmed", "id": ",".join(batch), "rettype": "abstract", "retmode": "xml"},
            timeout=30,
        )
        if r is None:
            continue

        try:
            root = ET.fromstring(r.content)
        except ET.ParseError as e:
            log.warning("PubMed XML parse error: %s", e)
            continue

        for article in root.findall(".//PubmedArticle"):
            med = article.find("MedlineCitation")
            if med is None:
                continue
            art = med.find("Article")
            if art is None:
                continue

            title_el = art.find("ArticleTitle")
            title = (title_el.text or "").strip() if title_el is not None else ""
            if not title:
                continue

            abstract_el = art.find(".//AbstractText")
            abstract = (abstract_el.text or "").strip() if abstract_el is not None else None

            # Authors
            authors: list[str] = []
            for auth in art.findall(".//Author"):
                last  = (auth.findtext("LastName")  or "").strip()
                first = (auth.findtext("ForeName")  or "").strip()
                if last:
                    authors.append(f"{first} {last}".strip())

            # DOI
            doi = None
            for loc in art.findall(".//ELocationID"):
                if loc.get("EIdType") == "doi":
                    doi = (loc.text or "").strip()
                    break

            # PMID
            pmid_el = med.find("PMID")
            pmid = (pmid_el.text or "").strip() if pmid_el is not None else ""

            # Date — try ArticleDate (electronic) then PubDate
            pub_date = ""
            for ad in art.findall("ArticleDate"):
                y = ad.findtext("Year") or ""
                m = ad.findtext("Month") or "01"
                d_str = ad.findtext("Day") or "01"
                if y:
                    pub_date = f"{y}-{m.zfill(2)}-{d_str.zfill(2)}"
                    break
            if not pub_date:
                journal = art.find("Journal")
                if journal is not None:
                    ji = journal.find("JournalIssue")
                    if ji is not None:
                        pd = ji.find("PubDate")
                        if pd is not None:
                            y = pd.findtext("Year") or ""
                            m = pd.findtext("Month") or "01"
                            if y:
                                pub_date = f"{y}-{m[:3]}-01"

            year = int(pub_date[:4]) if pub_date and pub_date[:4].isdigit() else None

            results.append(LitPaper(
                title=title,
                abstract=abstract,
                authors=authors,
                doi=doi,
                year=year,
                date=pub_date,
                source="pubmed",
                url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else f"https://doi.org/{doi}" if doi else "",
            ))

        time.sleep(0.1)  # Be kind to NCBI

    return results[:max_results]


# ── bioRxiv ───────────────────────────────────────────────────────────────────

_BIORXIV_API = "https://api.biorxiv.org/details/biorxiv"


def search_biorxiv(keywords: list[str], start: date, end: date, max_results: int = 100) -> list[LitPaper]:
    """
    Fetch bioRxiv papers in a date range then filter by keyword in title/abstract.
    bioRxiv's date API doesn't support keyword queries so we filter client-side.
    """
    kw_lower = [kw.lower() for kw in keywords]

    def _matches(title: str, abstract: str) -> bool:
        text = (title + " " + abstract).lower()
        return any(kw in text for kw in kw_lower)

    results: list[LitPaper] = []
    cursor = 0
    start_str = start.strftime("%Y-%m-%d")
    end_str   = end.strftime("%Y-%m-%d")

    while len(results) < max_results:
        r = _get(
            f"{_BIORXIV_API}/{start_str}/{end_str}/{cursor}/json",
            timeout=30,
        )
        if r is None:
            break

        try:
            data = r.json()
        except Exception as e:
            log.warning("bioRxiv JSON parse error: %s", e)
            break

        messages = data.get("messages", [{}])
        if not messages or messages[0].get("status") != "ok":
            log.info("bioRxiv returned non-ok status for %s–%s", start_str, end_str)
            break

        collection = data.get("collection", [])
        if not collection:
            break

        for item in collection:
            title    = (item.get("title") or "").strip()
            abstract = (item.get("abstract") or "").strip()
            if not title:
                continue
            if kw_lower and not _matches(title, abstract):
                continue

            doi       = (item.get("doi") or "").strip()
            authors_s = (item.get("authors") or "").strip()
            authors   = [a.strip() for a in authors_s.split(";") if a.strip()] if authors_s else []
            pub_date  = (item.get("date") or "")[:10]
            year      = int(pub_date[:4]) if pub_date and pub_date[:4].isdigit() else None

            results.append(LitPaper(
                title=title,
                abstract=abstract,
                authors=authors,
                doi=doi or None,
                year=year,
                date=pub_date,
                source="biorxiv",
                url=f"https://doi.org/{doi}" if doi else f"https://www.biorxiv.org/",
            ))
            if len(results) >= max_results:
                break

        total = int(messages[0].get("total", 0))
        count = int(messages[0].get("count", len(collection)))
        cursor += count
        if cursor >= total:
            break

    return results[:max_results]


# ── Library check ─────────────────────────────────────────────────────────────

def mark_existing(papers: list[LitPaper], driver: Driver) -> None:
    """Set already_in_library=True for any paper whose DOI is already in Neo4j."""
    for paper in papers:
        if paper.doi and not paper.doi.startswith("arXiv:"):
            if find_duplicate(driver, doi=paper.doi):
                paper.already_in_library = True
