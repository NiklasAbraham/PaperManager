import logging
import re
import httpx
from difflib import SequenceMatcher

from config import settings

log = logging.getLogger(__name__)

_SS_BASE = "https://api.semanticscholar.org/graph/v1/paper"
_CR_BASE = "https://api.crossref.org/works"
_FIELDS = "title,authors,authors.affiliations,year,venue,abstract,externalIds,citationCount"


def _strip_jats(text: str | None) -> str | None:
    """Strip JATS XML tags from CrossRef abstracts (e.g. <jats:p>, <jats:title>)."""
    if not text:
        return text
    cleaned = re.sub(r"<[^>]+>", " ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or None


def _ssl():
    if settings.ssl_ca_bundle:
        return settings.ssl_ca_bundle
    return settings.ssl_verify


def _title_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _parse_s2_authors(raw: list) -> tuple[list[str], list[dict]]:
    """Return (name_list, detail_list) from a S2 authors array.
    detail_list entries: {name, affiliation} — affiliation may be None.
    """
    names = []
    detail = []
    for a in raw:
        name = a.get("name", "").strip()
        if not name:
            continue
        affiliations = a.get("affiliations") or []
        aff = affiliations[0].get("name") if affiliations else None
        names.append(name)
        detail.append({"name": name, "affiliation": aff})
    return names, detail


def search_semantic_scholar_by_title(title: str) -> dict | None:
    """Search S2 by title; only return if a close match is found (similarity ≥ 0.85)."""
    try:
        r = httpx.get(
            f"{_SS_BASE}/search",
            params={"query": title, "fields": _FIELDS, "limit": 3},
            verify=_ssl(),
            timeout=10,
        )
        if r.status_code != 200:
            return None
        candidates = r.json().get("data") or []
        for data in candidates:
            candidate_title = (data.get("title") or "").strip()
            if _title_similarity(title, candidate_title) >= 0.85:
                doi = (data.get("externalIds") or {}).get("DOI") or title
                names, detail = _parse_s2_authors(data.get("authors") or [])
                return {
                    "title": candidate_title,
                    "year": data.get("year"),
                    "venue": data.get("venue"),
                    "abstract": data.get("abstract"),
                    "doi": doi,
                    "citation_count": data.get("citationCount"),
                    "authors": names,
                    "authors_detail": detail,
                    "topics": [],
                    "metadata_source": "semantic_scholar",
                }
        return None
    except Exception:
        return None


# ── Related papers (Semantic Scholar recommendations) ─────────────────────────

_S2_REC_BASE = "https://api.semanticscholar.org/recommendations/v1/papers/forpaper"
_S2_PAPER_BASE = "https://api.semanticscholar.org/graph/v1/paper"
_REC_FIELDS = "title,authors,year,abstract,externalIds,venue,citationCount"


def _get_s2_paper_id(doi: str) -> str | None:
    """
    Resolve a DOI or arXiv ID to a Semantic Scholar internal paperId.
    Returns paperId string or None on failure.
    """
    if not doi:
        return None

    # S2 requires a typed identifier prefix
    if doi.startswith("10."):
        s2_id = f"DOI:{doi}"
    elif doi.lower().startswith("arxiv:"):
        s2_id = doi
    else:
        s2_id = doi

    try:
        r = httpx.get(
            f"{_S2_PAPER_BASE}/{s2_id}",
            params={"fields": "paperId"},
            verify=_ssl(),
            timeout=10,
        )
        if r.status_code != 200:
            return None
        return r.json().get("paperId")
    except Exception:
        return None


def get_related_papers(doi: str, limit: int = 10) -> list[dict]:
    """
    Get related papers from Semantic Scholar recommendations API.
    Returns list of dicts with standard metadata format.
    """
    # Step 1: Resolve doi to S2 paperId
    paper_id = _get_s2_paper_id(doi)
    if not paper_id:
        return []

    # Step 2: Get recommendations
    try:
        r = httpx.get(
            f"{_S2_REC_BASE}/{paper_id}",
            params={"fields": _REC_FIELDS, "limit": limit},
            verify=_ssl(),
            timeout=15,
        )
        if r.status_code != 200:
            log.warning("S2 recommendations failed | paper_id=%s | status=%d", paper_id, r.status_code)
            return []

        recommendations = r.json().get("recommendedPapers", [])
        results = []

        for rec in recommendations:
            title = (rec.get("title") or "").strip()
            if not title:
                continue

            # Authors
            names, detail = _parse_s2_authors(rec.get("authors") or [])

            # DOI or arXiv ID
            ext_ids = rec.get("externalIds") or {}
            rec_doi = ext_ids.get("DOI")
            if not rec_doi and ext_ids.get("ArXiv"):
                rec_doi = f"arXiv:{ext_ids['ArXiv']}"

            # URL
            rec_paper_id = rec.get("paperId") or ""
            url = f"https://www.semanticscholar.org/paper/{rec_paper_id}" if rec_paper_id else ""

            results.append({
                "title": title,
                "authors": names,
                "year": rec.get("year"),
                "abstract": rec.get("abstract"),
                "doi": rec_doi,
                "url": url,
                "venue": rec.get("venue"),
                "citation_count": rec.get("citationCount"),
                "in_library": False,
                "library_paper_id": None,
            })

        return results
    except Exception as e:
        log.warning("S2 recommendations error | paper_id=%s | %s", paper_id, e)
        return []


def lookup_semantic_scholar(doi: str) -> dict | None:
    # S2 requires a typed identifier prefix; bare DOIs need "DOI:"
    if doi.startswith("10."):
        s2_id = f"DOI:{doi}"
    elif doi.lower().startswith("arxiv:"):
        s2_id = doi  # already prefixed
    else:
        s2_id = doi
    try:
        r = httpx.get(f"{_SS_BASE}/{s2_id}", params={"fields": _FIELDS}, verify=_ssl(), timeout=10)
        if r.status_code != 200:
            log.warning("S2 lookup failed | id=%s | status=%d | body=%.120s", s2_id, r.status_code, r.text)
            return None
        data = r.json()
        names, detail = _parse_s2_authors(data.get("authors") or [])
        return {
            "title": (data.get("title") or "").strip(),
            "year": data.get("year"),
            "venue": data.get("venue"),
            "abstract": data.get("abstract"),
            "doi": doi,
            "citation_count": data.get("citationCount"),
            "authors": names,
            "authors_detail": detail,
            "topics": [],
            "metadata_source": "semantic_scholar",
        }
    except Exception as e:
        log.warning("S2 lookup error | id=%s | %s", s2_id, e)
        return None


def lookup_crossref(doi: str) -> dict | None:
    try:
        r = httpx.get(f"{_CR_BASE}/{doi}", verify=_ssl(), timeout=10)
        if r.status_code != 200:
            log.warning("CrossRef lookup failed | doi=%s | status=%d", doi, r.status_code)
            return None
        msg = r.json().get("message", {})
        title_list = msg.get("title", [])
        authors_raw = msg.get("author", [])
        authors = [
            f"{a.get('given', '')} {a.get('family', '')}".strip()
            for a in authors_raw
        ]
        authors_detail = []
        for a in authors_raw:
            name = f"{a.get('given', '')} {a.get('family', '')}".strip()
            if not name:
                continue
            affs = a.get("affiliation") or []
            aff = affs[0].get("name") if affs else None
            authors_detail.append({"name": name, "affiliation": aff})
        container = msg.get("container-title", [])
        year = None
        pub = msg.get("published", {}).get("date-parts", [[]])
        if pub and pub[0]:
            year = pub[0][0]
        return {
            "title": title_list[0].strip() if title_list else "",
            "year": year,
            "venue": container[0] if container else None,
            "abstract": _strip_jats(msg.get("abstract")),
            "doi": doi,
            "citation_count": None,
            "authors": authors,
            "authors_detail": authors_detail,
            "topics": [],
            "metadata_source": "crossref",
        }
    except Exception:
        return None
