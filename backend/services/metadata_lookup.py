import httpx

_SS_BASE = "https://api.semanticscholar.org/graph/v1/paper"
_CR_BASE = "https://api.crossref.org/works"
_FIELDS = "title,authors,year,venue,abstract,externalIds,citationCount"


def lookup_semantic_scholar(doi: str) -> dict | None:
    try:
        r = httpx.get(f"{_SS_BASE}/{doi}", params={"fields": _FIELDS}, timeout=10)
        if r.status_code != 200:
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
            "topics": [],  # S2 deprecated fieldsOfStudy in this endpoint
            "metadata_source": "semantic_scholar",
        }
    except Exception:
        return None


def lookup_crossref(doi: str) -> dict | None:
    try:
        r = httpx.get(f"{_CR_BASE}/{doi}", timeout=10)
        if r.status_code != 200:
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
