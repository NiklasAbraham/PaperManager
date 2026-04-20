"""Bulk import resolver — resolve a single JSON entry to paper metadata + optional PDF."""
from __future__ import annotations

import re
import logging
import xml.etree.ElementTree as ET

import httpx

from services.metadata_from_url import resolve_url, _get, _ssl_verify, _UA
from services.metadata_lookup import search_semantic_scholar_by_title

log = logging.getLogger(__name__)

_ARXIV_ID_RE = re.compile(r"^(?:arxiv[:\s])?(\d{4}\.\d{4,5}(?:v\d+)?)$", re.I)


def _try_arxiv_title_search(title: str) -> dict | None:
    """Search arXiv by title and return metadata for the top result."""
    r = _get(
        "https://export.arxiv.org/api/query",
        params={"search_query": f"ti:{title}", "max_results": 1},
    )
    if r is None:
        return None
    try:
        root = ET.fromstring(r.content)
        ns = {
            "atom": "http://www.w3.org/2005/Atom",
            "arxiv": "http://arxiv.org/schemas/atom",
        }
        entry = root.find(".//atom:entry", ns)
        if entry is None:
            return None
        entry_title = (entry.findtext("atom:title", "", ns) or "").strip()
        if not entry_title:
            return None
        entry_id_url = entry.findtext("atom:id", "", ns) or ""
        m = re.search(r"abs/(\d{4}\.\d{4,5}(?:v\d+)?)", entry_id_url)
        if not m:
            return None
        return resolve_url(f"https://arxiv.org/abs/{m.group(1)}")
    except Exception as e:
        log.warning("arXiv title search parse error | %s", e)
        return None


def _ollama_suggest_arxiv_query(title: str) -> str | None:
    """Use Ollama to suggest a clean arXiv title search query for a paper title."""
    try:
        import ollama
        from config import settings
        response = ollama.chat(
            model=settings.ollama_model,
            messages=[{
                "role": "user",
                "content": (
                    f'I want to find this paper on arXiv: "{title}"\n'
                    "Give me only the best short search query to find it (3-6 keywords). "
                    "Output ONLY the query text, nothing else."
                ),
            }],
        )
        query = (response.message.content or "").strip().strip('"')
        return query if query else None
    except Exception as e:
        log.warning("Ollama query suggestion failed | %s", e)
        return None


def resolve_entry(entry: dict) -> dict | None:
    """
    Resolve a bulk import entry to normalised paper metadata.

    Entry fields (at least one required): url, arxiv, doi, title
    Returns metadata dict or None if unresolvable.
    """
    # 1. Direct URL (arXiv URL, DOI URL, PubMed URL, bioRxiv URL)
    if entry.get("url"):
        return resolve_url(str(entry["url"]).strip())

    # 2. arXiv ID (bare or prefixed)
    if entry.get("arxiv"):
        arxiv_raw = str(entry["arxiv"]).strip()
        m = _ARXIV_ID_RE.match(arxiv_raw)
        if m:
            return resolve_url(f"https://arxiv.org/abs/{m.group(1)}")
        # May already be a full arXiv URL
        return resolve_url(arxiv_raw)

    # 3. DOI (bare "10.xxx/..." or full URL)
    if entry.get("doi"):
        return resolve_url(str(entry["doi"]).strip())

    # 4. Title-only: S2 → arXiv → Ollama+arXiv
    if entry.get("title"):
        title = str(entry["title"]).strip()
        log.info("Title-only resolve | title=%.80s", title)

        meta = search_semantic_scholar_by_title(title)
        if meta and meta.get("title"):
            log.info("Resolved via S2 title search | title=%.60s", meta["title"])
            return meta

        meta = _try_arxiv_title_search(title)
        if meta and meta.get("title"):
            log.info("Resolved via arXiv title search | title=%.60s", meta["title"])
            return meta

        improved = _ollama_suggest_arxiv_query(title)
        if improved and improved.lower() != title.lower():
            log.info("Trying Ollama-improved arXiv query | query=%.60s", improved)
            meta = _try_arxiv_title_search(improved)
            if meta and meta.get("title"):
                log.info("Resolved via Ollama+arXiv | title=%.60s", meta["title"])
                return meta

        log.warning("Could not resolve title-only entry | title=%.80s", title)
        return None

    log.warning("Bulk entry has no resolvable field | entry=%s", entry)
    return None


def download_pdf_for_paper(meta: dict) -> bytes | None:
    """
    Try to download a PDF for the resolved metadata.
    Returns raw PDF bytes or None if unavailable.

    Tries:
      1. arXiv PDF (when doi starts with "arXiv:")
      2. Unpaywall open-access PDF (when a real DOI is available)
    """
    doi = meta.get("doi") or ""

    # --- arXiv PDF ---
    if doi.lower().startswith("arxiv:"):
        arxiv_id = re.sub(r"v\d+$", "", doi[6:].strip())
        if arxiv_id:
            pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"
            log.info("Downloading arXiv PDF | id=%s", arxiv_id)
            r = _get(pdf_url, timeout=60, retries=2, backoff=3.0)
            if r and r.headers.get("content-type", "").lower().startswith("application/pdf"):
                return r.content
            # arXiv sometimes redirects; check content length as fallback
            if r and len(r.content) > 10_000:
                return r.content

    # --- Unpaywall open-access PDF ---
    if doi.startswith("10."):
        log.info("Checking Unpaywall for OA PDF | doi=%s", doi)
        r = _get(
            f"https://api.unpaywall.org/v2/{doi}",
            params={"email": "papermanager@local"},
            timeout=15,
        )
        if r:
            try:
                data = r.json()
                best = data.get("best_oa_location") or {}
                pdf_url = best.get("url_for_pdf")
                if pdf_url:
                    log.info("Downloading OA PDF via Unpaywall | url=%.80s", pdf_url)
                    pr = _get(pdf_url, timeout=60, retries=1, backoff=2.0)
                    if pr and len(pr.content) > 10_000:
                        return pr.content
            except Exception as e:
                log.warning("Unpaywall parse error | %s", e)

    log.info("No PDF available for paper | doi=%s", doi)
    return None
