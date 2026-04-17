import logging
import httpx
from difflib import SequenceMatcher

from config import settings

log = logging.getLogger(__name__)

_SS_BASE = "https://api.semanticscholar.org/graph/v1/paper"
_CR_BASE = "https://api.crossref.org/works"
_FIELDS = "title,authors,year,venue,abstract,externalIds,citationCount"


def _ssl():
    if settings.ssl_ca_bundle:
        return settings.ssl_ca_bundle
    return settings.ssl_verify


def _title_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


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
                return {
                    "title": candidate_title,
                    "year": data.get("year"),
                    "venue": data.get("venue"),
                    "abstract": data.get("abstract"),
                    "doi": doi,
                    "citation_count": data.get("citationCount"),
                    "authors": [a.get("name", "") for a in (data.get("authors") or [])],
                    "topics": [],
                    "metadata_source": "semantic_scholar",
                }
        return None
    except Exception:
        return None


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
        return {
            "title": (data.get("title") or "").strip(),
            "year": data.get("year"),
            "venue": data.get("venue"),
            "abstract": data.get("abstract"),
            "doi": doi,
            "citation_count": data.get("citationCount"),
            "authors": [
                a.get("name", "") for a in (data.get("authors") or [])
            ],
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
        container = msg.get("container-title", [])
        year = None
        pub = msg.get("published", {}).get("date-parts", [[]])
        if pub and pub[0]:
            year = pub[0][0]
        return {
            "title": title_list[0].strip() if title_list else "",
            "year": year,
            "venue": container[0] if container else None,
            "abstract": msg.get("abstract"),
            "doi": doi,
            "citation_count": None,
            "authors": authors,
            "topics": [],
            "metadata_source": "crossref",
        }
    except Exception:
        return None
