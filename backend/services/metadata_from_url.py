"""
Resolve paper metadata from a URL or identifier.

Supported inputs:
  - arXiv URL:   https://arxiv.org/abs/2603.11703  (or /pdf/...)
  - arXiv ID:    2603.11703  or  arXiv:2603.11703
  - DOI URL:     https://doi.org/10.1038/...
  - Plain DOI:   10.1038/...
  - PubMed URL:  https://pubmed.ncbi.nlm.nih.gov/12345678/
  - bioRxiv URL: https://www.biorxiv.org/content/10.1101/...
  - medRxiv URL: https://www.medrxiv.org/content/10.1101/...
"""

import re
import time
import logging
import xml.etree.ElementTree as ET

import httpx

from services.metadata_lookup import lookup_semantic_scholar, lookup_crossref
from config import settings


def _ssl_verify():
    """Return the httpx ssl verify value from settings."""
    if settings.ssl_ca_bundle:
        return settings.ssl_ca_bundle
    return settings.ssl_verify

log = logging.getLogger(__name__)

# ── Regexes ───────────────────────────────────────────────────────────────────

_ARXIV_URL  = re.compile(r"arxiv\.org/(?:abs|pdf|html)/(\d{4}\.\d{4,5}(?:v\d+)?)", re.I)
_ARXIV_ID   = re.compile(r"^(?:arxiv[:\s])?(\d{4}\.\d{4,5}(?:v\d+)?)$", re.I)
_DOI_URL    = re.compile(r"(?:https?://)?(?:dx\.)?doi\.org/(10\.\d{4,9}/.+)")
_DOI_BARE   = re.compile(r"^(10\.\d{4,9}/.+)")
_PUBMED_URL = re.compile(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)")
_BIORXIV    = re.compile(r"(biorxiv|medrxiv)\.org/content/(10\.\d{4,9}/[^\s?#v]+)")

# Browser-like User-Agent — arXiv blocks default httpx/requests agents
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


# ── Retry helper ──────────────────────────────────────────────────────────────

def _get(url: str, *, params: dict | None = None, timeout: int = 15,
         retries: int = 3, backoff: float = 5.0) -> httpx.Response | None:
    """GET with exponential-backoff retry (ported from literature/retrieval)."""
    delay = backoff
    for attempt in range(retries):
        try:
            r = httpx.get(url, params=params,
                          headers={"User-Agent": _UA},
                          verify=_ssl_verify(),
                          timeout=timeout)
            r.raise_for_status()
            return r
        except Exception as e:
            if attempt < retries - 1:
                log.warning("HTTP error (attempt %d/%d): %s — retrying in %.0fs",
                            attempt + 1, retries, e, delay)
                time.sleep(delay)
                delay *= 2
            else:
                log.warning("HTTP failed after %d attempts | url=%s | %s", retries, url, e)
    return None


# ── arXiv ─────────────────────────────────────────────────────────────────────

def _fetch_arxiv(arxiv_id: str) -> dict | None:
    """Fetch a single arXiv paper by ID using the id_list parameter (more reliable than search_query=id:)."""
    clean = re.sub(r"v\d+$", "", arxiv_id)
    r = _get(
        "https://export.arxiv.org/api/query",
        params={"id_list": clean, "max_results": 1},
    )
    if r is None:
        return None

    root = ET.fromstring(r.content)
    ns = {
        "atom":  "http://www.w3.org/2005/Atom",
        "arxiv": "http://arxiv.org/schemas/atom",
    }
    entry = root.find(".//atom:entry", ns)
    if entry is None:
        log.warning("arXiv returned no entry for id=%s", clean)
        return None

    def _norm(s: str) -> str:
        """Normalize whitespace: collapse all runs of whitespace to a single space."""
        return re.sub(r"\s+", " ", s).strip()

    title     = _norm(entry.findtext("atom:title",   "", ns) or "")
    abstract  = _norm(entry.findtext("atom:summary", "", ns) or "")
    published = entry.findtext("atom:published", "", ns) or ""
    year      = int(published[:4]) if len(published) >= 4 else None

    authors = []
    for author in entry.findall("atom:author", ns):
        name = author.findtext("atom:name", "", ns)
        if name:
            authors.append(name.strip())

    # Prefer a real DOI link if the paper has been published
    doi: str | None = None
    for link in entry.findall("atom:link", ns):
        if link.get("title") == "doi":
            doi = link.get("href", "").replace("https://doi.org/", "")
    if not doi:
        doi = f"arXiv:{clean}"

    venue_tag = entry.find("arxiv:journal_ref", ns)
    venue = venue_tag.text.strip() if venue_tag is not None and venue_tag.text else "arXiv"

    result = {
        "title": title,
        "abstract": abstract or None,
        "year": year,
        "authors": authors,
        "doi": doi,
        "venue": venue,
        "citation_count": None,
        "topics": [],
        "metadata_source": "arxiv",
    }

    # Upgrade via Semantic Scholar for richer metadata (citation count, affiliations)
    # especially if authors or abstract are missing from the Atom feed
    if not authors or not abstract:
        log.info("arXiv Atom missing authors/abstract — trying S2 upgrade | id=%s", clean)
        s2 = lookup_semantic_scholar(doi)
        if s2 and s2.get("title"):
            # Merge: keep arXiv fields where S2 is missing, fill gaps from S2
            for key in ("authors", "abstract", "citation_count", "authors_detail"):
                if not result.get(key) and s2.get(key):
                    result[key] = s2[key]
            if s2.get("metadata_source"):
                result["metadata_source"] = "arxiv+s2"

    return result


# ── bioRxiv / medRxiv ─────────────────────────────────────────────────────────

def _fetch_biorxiv(doi: str, server: str = "biorxiv") -> dict | None:
    """
    Fetch a specific preprint from the native bioRxiv/medRxiv API by DOI.
    Endpoint: GET https://api.biorxiv.org/details/{server}/{doi}/na/json
    """
    r = _get(f"https://api.biorxiv.org/details/{server}/{doi}/na/json")
    if r is None:
        return None
    try:
        data = r.json()
        collection = data.get("collection") or []
        if not collection:
            return None
        paper = collection[-1]  # take the latest version

        # Parse year from date string
        date_str = paper.get("date", "")
        year = int(date_str[:4]) if len(date_str) >= 4 else None

        # Authors: "First Last, First Last, ..."
        authors_raw = paper.get("authors", "") or ""
        authors = [a.strip() for a in authors_raw.split(";") if a.strip()]

        return {
            "title":          re.sub(r"\s+", " ", paper.get("title") or "").strip(),
            "abstract":       re.sub(r"\s+", " ", paper.get("abstract") or "").strip() or None,
            "year":           year,
            "authors":        authors,
            "doi":            paper.get("doi") or doi,
            "venue":          paper.get("server") or server,
            "citation_count": None,
            "topics":         [],
            "metadata_source": server,
        }
    except Exception as e:
        log.warning("bioRxiv parse error | doi=%s | %s", doi, e)
        return None


# ── PubMed ────────────────────────────────────────────────────────────────────

def _fetch_pubmed(pmid: str) -> dict | None:
    r = _get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
        params={"db": "pubmed", "id": pmid, "rettype": "abstract", "retmode": "xml"},
    )
    if r is None:
        return None

    try:
        root = ET.fromstring(r.content)
        article = root.find(".//Article")
        if article is None:
            return None

        title = (article.findtext("ArticleTitle") or "").strip()

        abstract_parts = [(el.text or "") for el in article.findall(".//AbstractText")]
        abstract = " ".join(p.strip() for p in abstract_parts if p.strip()) or None

        year = None
        for date_path in [".//ArticleDate", ".//PubDate"]:
            year_el = root.find(f"{date_path}/Year")
            if year_el is not None and year_el.text:
                year = int(year_el.text)
                break

        authors = []
        for auth in root.findall(".//Author"):
            last  = (auth.findtext("LastName") or "").strip()
            first = (auth.findtext("ForeName") or "").strip()
            name  = f"{first} {last}".strip()
            if name:
                authors.append(name)

        doi = None
        for loc in root.findall(".//ELocationID"):
            if loc.get("EIdType") == "doi":
                doi = (loc.text or "").strip()
                break

        venue = root.findtext(".//Journal/Title") or root.findtext(".//MedlineTA")

        return {
            "title":          title,
            "abstract":       abstract,
            "year":           year,
            "authors":        authors,
            "doi":            doi,
            "venue":          venue,
            "citation_count": None,
            "topics":         [],
            "metadata_source": "pubmed",
        }
    except Exception as e:
        log.warning("PubMed XML parse error | pmid=%s | %s", pmid, e)
        return None


# ── DOI resolver (S2 → CrossRef, merging gaps) ────────────────────────────────

def _resolve_doi(doi: str) -> dict | None:
    """Resolve a DOI via S2 then CrossRef, merging the two to fill any gaps."""
    s2 = lookup_semantic_scholar(doi)
    cr = lookup_crossref(doi)

    if not s2 and not cr:
        return None
    if not s2:
        return cr
    if not cr:
        return s2

    # Both succeeded — start with S2 (richer: citation count, affiliations)
    # then fill any missing fields from CrossRef
    result = dict(s2)
    for key in ("authors", "abstract", "year", "venue", "authors_detail"):
        if not result.get(key) and cr.get(key):
            log.info("Filling missing %s from CrossRef | doi=%s", key, doi)
            result[key] = cr[key]
    return result


# ── Main resolver ─────────────────────────────────────────────────────────────

def resolve_url(url: str) -> dict | None:
    """
    Given a URL or identifier string, return normalised paper metadata.
    Returns None if the source cannot be resolved.
    """
    url = url.strip()

    # --- arXiv URL ----------------------------------------------------------
    m = _ARXIV_URL.search(url)
    if m:
        log.info("Resolving arXiv URL | id=%s", m.group(1))
        return _fetch_arxiv(m.group(1))

    # --- bare arXiv ID ------------------------------------------------------
    m = _ARXIV_ID.match(url)
    if m:
        log.info("Resolving arXiv ID | id=%s", m.group(1))
        return _fetch_arxiv(m.group(1))

    # --- DOI URL (doi.org/...) ---------------------------------------------
    m = _DOI_URL.search(url)
    if m:
        doi = m.group(1).rstrip(".,;)")
        log.info("Resolving DOI URL | doi=%s", doi)
        return _resolve_doi(doi)

    # --- bare DOI (10.xxxx/...) --------------------------------------------
    m = _DOI_BARE.match(url)
    if m:
        doi = m.group(1).rstrip(".,;)")
        log.info("Resolving bare DOI | doi=%s", doi)
        return _resolve_doi(doi)

    # --- PubMed URL ---------------------------------------------------------
    m = _PUBMED_URL.search(url)
    if m:
        log.info("Resolving PubMed | pmid=%s", m.group(1))
        result = _fetch_pubmed(m.group(1))
        # Upgrade via S2/CrossRef if we got a DOI (richer metadata + citation count)
        if result and result.get("doi"):
            enriched = _resolve_doi(result["doi"])
            if enriched and enriched.get("title"):
                # Fill PubMed gaps from DOI lookup; PubMed abstract is usually best
                for key in ("authors", "authors_detail", "citation_count", "venue"):
                    if not result.get(key) and enriched.get(key):
                        result[key] = enriched[key]
                if not result.get("abstract") and enriched.get("abstract"):
                    result["abstract"] = enriched["abstract"]
        return result

    # --- bioRxiv / medRxiv URL (DOI embedded in path) ----------------------
    m = _BIORXIV.search(url)
    if m:
        server = m.group(1).lower()   # "biorxiv" or "medrxiv"
        doi    = m.group(2).rstrip(".,;)")
        log.info("Resolving %s | doi=%s", server, doi)
        # Try native bioRxiv API first, fall back to S2/CrossRef
        result = _fetch_biorxiv(doi, server)
        if result and result.get("title"):
            return result
        return _resolve_doi(doi)

    log.warning("Could not identify URL type | url=%.80s", url)
    return None


# ── PDF download ──────────────────────────────────────────────────────────────

def fetch_pdf_bytes(url: str) -> bytes | None:
    """
    Try to download the PDF for an arXiv or bioRxiv/medRxiv URL.
    Returns raw PDF bytes, or None if the source doesn't provide an open PDF.
    """
    url = url.strip()

    # arXiv → https://arxiv.org/pdf/{id}
    m = _ARXIV_URL.search(url) or _ARXIV_ID.match(url)
    if m:
        arxiv_id = re.sub(r"v\d+$", "", m.group(1))
        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"
        log.info("Downloading arXiv PDF | url=%s", pdf_url)
        r = _get(pdf_url, timeout=60)
        if r and r.content[:4] == b"%PDF":
            return r.content
        log.warning("arXiv PDF download is not a PDF | content-type=%s | first_bytes=%s",
                    r.headers.get("content-type") if r else None,
                    r.content[:20] if r else None)
        return None

    # bioRxiv / medRxiv → {content_url}.full.pdf
    m = _BIORXIV.search(url)
    if m:
        site = m.group(1)
        doi_path = m.group(2)
        # Extract version from URL if present (e.g. …123456v2)
        ver_m = re.search(r"(v\d+)(?:[?#]|$)", url[url.find(doi_path):])
        ver = ver_m.group(1) if ver_m else ""
        pdf_url = f"https://www.{site}.org/content/{doi_path}{ver}.full.pdf"
        log.info("Downloading %s PDF | url=%s", site, pdf_url)
        # bioRxiv CDN requires Referer + Accept headers to avoid 403
        try:
            r = httpx.get(
                pdf_url,
                headers={
                    "User-Agent": _UA,
                    "Referer": f"https://www.{site}.org/content/{doi_path}{ver}",
                    "Accept": "application/pdf,*/*",
                },
                verify=_ssl_verify(),
                timeout=60,
                follow_redirects=True,
            )
            r.raise_for_status()
            if r.content[:4] == b"%PDF":
                return r.content
            log.warning("%s PDF is not a PDF | content-type=%s | first_bytes=%s",
                        site, r.headers.get("content-type"), r.content[:20])
        except Exception as e:
            log.warning("%s PDF download failed | url=%s | %s", site, pdf_url, e)

    return None
