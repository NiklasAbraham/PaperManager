"""Person profile enrichment service.

Extracts ORCID / Google Scholar links from paper text and fetches
affiliation + citation count from the ORCID public API and Semantic Scholar.
"""

import logging
import re
from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher

import httpx

from config import settings

log = logging.getLogger(__name__)

_ORCID_RE = re.compile(r"orcid\.org/([\dX]{4}-[\dX]{4}-[\dX]{4}-[\dX]{4})", re.IGNORECASE)
_SCHOLAR_RE = re.compile(
    r"scholar\.google\.com/citations\?(?:[^\">\s]*&)?user=([\w-]+)", re.IGNORECASE
)
_S2_AUTHOR_BASE = "https://api.semanticscholar.org/graph/v1/author"
_ORCID_API_BASE = "https://pub.orcid.org/v3.0"
_ENRICH_COOLDOWN_HOURS = 24


def _ssl():
    if settings.ssl_ca_bundle:
        return settings.ssl_ca_bundle
    return settings.ssl_verify


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _match_name(a: str, b: str) -> bool:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio() >= 0.75


def _extract_orcid_ids(text: str) -> list[str]:
    return list(dict.fromkeys(_ORCID_RE.findall(text)))  # deduplicated, order-preserved


def _extract_scholar_user_ids(text: str) -> list[str]:
    return list(dict.fromkeys(_SCHOLAR_RE.findall(text)))


def _fetch_orcid_profile(orcid_id: str) -> dict | None:
    """Fetch name, affiliation, works count from ORCID public API (no auth needed)."""
    try:
        r = httpx.get(
            f"{_ORCID_API_BASE}/{orcid_id}/record",
            headers={"Accept": "application/json"},
            verify=_ssl(),
            timeout=8,
        )
        if r.status_code != 200:
            log.debug("ORCID fetch failed | orcid=%s | status=%d", orcid_id, r.status_code)
            return None
        data = r.json()

        # Name
        name_section = (data.get("person") or {}).get("name") or {}
        given = (name_section.get("given-names") or {}).get("value", "")
        family = (name_section.get("family-name") or {}).get("value", "")
        full_name = f"{given} {family}".strip()

        # Affiliation — first employment record
        affiliations = (
            (data.get("activities-summary") or {})
            .get("employments", {})
            .get("affiliation-group", [])
        )
        affiliation = None
        for grp in affiliations:
            summaries = grp.get("summaries", [])
            for s in summaries:
                org = (s.get("employment-summary") or {}).get("organization") or {}
                org_name = org.get("name")
                if org_name:
                    affiliation = org_name
                    break
            if affiliation:
                break

        # Works count (used as a proxy for citation count when S2 data unavailable)
        works_group = (
            (data.get("activities-summary") or {}).get("works", {}).get("group", [])
        )
        works_count = len(works_group)

        return {
            "name": full_name,
            "affiliation": affiliation,
            "works_count": works_count,
            "orcid_url": f"https://orcid.org/{orcid_id}",
        }
    except Exception as exc:
        log.debug("ORCID fetch error | orcid=%s | %s", orcid_id, exc)
        return None


def _fetch_s2_author(s2_author_id: str) -> dict | None:
    """Fetch name, affiliation, citation count from Semantic Scholar."""
    try:
        r = httpx.get(
            f"{_S2_AUTHOR_BASE}/{s2_author_id}",
            params={"fields": "name,affiliations,citationCount,paperCount"},
            verify=_ssl(),
            timeout=8,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        affiliations = data.get("affiliations") or []
        aff = affiliations[0].get("name") if affiliations else None
        return {
            "name": data.get("name", ""),
            "affiliation": aff,
            "citation_count": data.get("citationCount"),
        }
    except Exception as exc:
        log.debug("S2 author fetch error | s2_id=%s | %s", s2_author_id, exc)
        return None


def _update_person_node(driver, person_id: str, props: dict):
    """Apply a props dict to a Person node, skipping None values."""
    clean = {k: v for k, v in props.items() if v is not None}
    if not clean:
        return
    with driver.session() as session:
        session.run(
            "MATCH (p:Person {id: $id}) SET p += $props",
            id=person_id,
            props=clean,
        )


def enrich_person_from_text(driver, person_id: str, raw_text: str) -> bool:
    """Try to find ORCID/Scholar links in raw_text that match this person.

    Returns True if any enrichment was applied.
    """
    if not raw_text:
        return False

    from db.queries.people import get_person  # avoid circular at module level
    person = get_person(driver, person_id)
    if not person:
        return False

    person_name = person.get("name", "")
    enriched = False
    props: dict = {}

    # --- ORCID ---
    orcid_ids = _extract_orcid_ids(raw_text)
    for orcid_id in orcid_ids:
        profile = _fetch_orcid_profile(orcid_id)
        if not profile:
            continue
        if not _match_name(person_name, profile["name"]):
            continue
        # Match found
        if not person.get("orcid_url"):
            props["orcid_url"] = profile["orcid_url"]
        if not person.get("affiliation") and profile.get("affiliation"):
            props["affiliation"] = profile["affiliation"]
        # ORCID works count is a rough proxy; only set if no real citation_count yet
        if not person.get("citation_count") and profile.get("works_count"):
            props["citation_count"] = profile["works_count"]
        enriched = True
        break  # stop after first matched ORCID

    # --- Google Scholar URL (store URL only, no API available) ---
    if not person.get("scholar_url"):
        scholar_ids = _extract_scholar_user_ids(raw_text)
        if scholar_ids:
            props["scholar_url"] = (
                f"https://scholar.google.com/citations?user={scholar_ids[0]}"
            )
            enriched = True

    # --- S2 fallback for citation count ---
    if not enriched and person.get("s2_author_id") and not person.get("citation_count"):
        s2 = _fetch_s2_author(person["s2_author_id"])
        if s2:
            if not person.get("affiliation") and s2.get("affiliation"):
                props["affiliation"] = s2["affiliation"]
            if s2.get("citation_count"):
                props["citation_count"] = s2["citation_count"]
            if props:
                enriched = True

    if props:
        props["last_enriched_at"] = _now()
        _update_person_node(driver, person_id, props)
        log.info("Enriched person | id=%s | name=%s | fields=%s", person_id, person_name, list(props))

    return enriched


def enrich_authors_from_paper(driver, paper_id: str, raw_text: str):
    """Enrich all authors of a paper from its raw text."""
    from db.queries.people import get_authors_for_paper
    authors = get_authors_for_paper(driver, paper_id)
    for author in authors:
        try:
            enrich_person_from_text(driver, author["id"], raw_text)
        except Exception as exc:
            log.warning("Error enriching author | id=%s | %s", author.get("id"), exc)


def enrich_person_by_id(driver, person_id: str) -> dict:
    """Re-run enrichment for a person using their stored orcid_url or s2_author_id.

    Skips if enriched within the last ENRICH_COOLDOWN_HOURS hours.
    Returns a result dict.
    """
    from db.queries.people import get_person
    person = get_person(driver, person_id)
    if not person:
        return {"person_id": person_id, "enriched": False, "message": "Person not found"}

    # Cooldown check
    last = person.get("last_enriched_at")
    if last:
        try:
            last_dt = datetime.fromisoformat(last)
            if datetime.now(timezone.utc) - last_dt < timedelta(hours=_ENRICH_COOLDOWN_HOURS):
                return {
                    "person_id": person_id,
                    "enriched": False,
                    "message": f"Skipped — enriched less than {_ENRICH_COOLDOWN_HOURS}h ago",
                }
        except Exception:
            pass

    props: dict = {}

    # Try ORCID if URL is stored
    orcid_url = person.get("orcid_url", "")
    if orcid_url:
        m = _ORCID_RE.search(orcid_url)
        if m:
            profile = _fetch_orcid_profile(m.group(1))
            if profile:
                if not person.get("affiliation") and profile.get("affiliation"):
                    props["affiliation"] = profile["affiliation"]
                if profile.get("works_count") and not person.get("citation_count"):
                    props["citation_count"] = profile["works_count"]

    # Try S2 for citation count (more accurate than ORCID works count)
    if person.get("s2_author_id"):
        s2 = _fetch_s2_author(person["s2_author_id"])
        if s2:
            if not person.get("affiliation") and s2.get("affiliation"):
                props["affiliation"] = s2["affiliation"]
            if s2.get("citation_count") is not None:
                props["citation_count"] = s2["citation_count"]  # always refresh from S2

    # Try Ollama from paper texts for any fields still missing
    try:
        ollama_props = enrich_person_from_papers_ollama(driver, person_id)
        props.update({k: v for k, v in ollama_props.items() if k not in props})
    except Exception as exc:
        log.debug("Ollama enrichment skipped | %s", exc)

    if props:
        props["last_enriched_at"] = _now()
        _update_person_node(driver, person_id, props)
        return {
            "person_id": person_id,
            "enriched": True,
            "affiliation": props.get("affiliation"),
            "citation_count": props.get("citation_count"),
            "orcid_url": person.get("orcid_url") or props.get("orcid_url"),
            "message": "OK",
        }

    # Nothing to update but mark as checked
    _update_person_node(driver, person_id, {"last_enriched_at": _now()})
    return {"person_id": person_id, "enriched": False, "message": "No new data found"}


_OLLAMA_PROMPT = """\
You are extracting professional profile information about a specific researcher from academic paper text.

Researcher name: {name}

Paper text (excerpt):
{text}

Extract any information about this researcher that appears in the text.
Return ONLY valid JSON with these optional fields (omit fields you cannot find):
{{
  "affiliation": "Institution or company name",
  "bio": "Short professional description or research focus (1-2 sentences)",
  "skills": ["skill1", "skill2"]
}}

Only include information that is clearly stated or strongly implied about THIS researcher.
If you find nothing useful, return {{}}.
"""


def _enrich_person_with_ollama(person_name: str, raw_text: str) -> dict:
    """Use Ollama to extract profile info about a named person from text.

    Returns a dict with any of: affiliation, bio, skills (list).
    Returns empty dict on failure or if nothing found.
    """
    import json as _json
    snippet = raw_text[:5000]  # keep prompt manageable
    prompt = _OLLAMA_PROMPT.format(name=person_name, text=snippet)
    try:
        import ollama
        resp = ollama.chat(
            model=settings.ollama_model,
            messages=[{"role": "user", "content": prompt}],
            format="json",
        )
        raw = resp["message"]["content"] if isinstance(resp, dict) else resp.message.content
        data = _json.loads(raw.strip())
        if not isinstance(data, dict):
            return {}
        result: dict = {}
        if isinstance(data.get("affiliation"), str) and data["affiliation"].strip():
            result["affiliation"] = data["affiliation"].strip()
        if isinstance(data.get("bio"), str) and data["bio"].strip():
            result["bio"] = data["bio"].strip()
        if isinstance(data.get("skills"), list):
            skills = [s for s in data["skills"] if isinstance(s, str) and s.strip()]
            if skills:
                import json
                result["skills"] = json.dumps(skills)
        return result
    except Exception as exc:
        log.debug("Ollama person enrichment error | name=%s | %s", person_name, exc)
        return {}


def enrich_person_from_papers_ollama(driver, person_id: str) -> dict:
    """Scan raw_text of all papers connected to this person and use Ollama to extract
    affiliation, bio, and skills. Only fills in fields that are currently empty.

    Returns dict of newly set fields (may be empty).
    """
    from db.queries.people import get_person, get_papers_by_person
    from db.queries.papers import get_paper

    person = get_person(driver, person_id)
    if not person:
        return {}

    person_name = person.get("name", "")
    papers = get_papers_by_person(driver, person_id)

    merged: dict = {}
    needs = {
        "affiliation": not person.get("affiliation"),
        "bio": not person.get("bio"),
        "skills": not person.get("skills") or person.get("skills") == "[]",
    }

    if not any(needs.values()):
        log.debug("Ollama enrich skipped — all fields already set | person=%s", person_id)
        return {}

    for paper_link in papers:
        paper = get_paper(driver, paper_link["id"])
        if not paper:
            continue
        raw_text = paper.get("raw_text") or ""
        if not raw_text.strip():
            continue

        extracted = _enrich_person_with_ollama(person_name, raw_text)
        for field, value in extracted.items():
            if needs.get(field) and field not in merged:
                merged[field] = value

        # Stop early if all needed fields are filled
        if all(field in merged for field in needs if needs[field]):
            break

    if merged:
        _update_person_node(driver, person_id, merged)
        log.info("Ollama enriched person | id=%s | fields=%s", person_id, list(merged))

    return merged


def enrich_all_people(driver) -> dict:
    """Enrich all people connected to at least one paper.

    For each person:
    - ORCID/S2 API lookup if they have stored orcid_url or s2_author_id
    - Ollama scan of connected paper texts for affiliation, bio, skills
    """
    with driver.session() as session:
        result = session.run(
            """
            MATCH (p:Person)
            WHERE ()-[:AUTHORED_BY|INVOLVES]->(p)
            RETURN p.id AS id
            """
        )
        person_ids = [r["id"] for r in result]

    enriched_count = 0
    error_count = 0
    for person_id in person_ids:
        try:
            # ORCID / S2 enrichment (only runs if person has those IDs)
            res = enrich_person_by_id(driver, person_id)
            ollama_res = enrich_person_from_papers_ollama(driver, person_id)
            if res.get("enriched") or ollama_res:
                enriched_count += 1
        except Exception as exc:
            log.warning("enrich_all_people error | id=%s | %s", person_id, exc)
            error_count += 1

    return {"enriched": enriched_count, "errors": error_count, "total": len(person_ids)}
