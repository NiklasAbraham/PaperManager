"""Researcher CV: build a person's career profile and check it against the library.

Sources: OpenAlex (author profile, affiliation history, metrics, works), ORCID
(employments, education, biography, homepage links) and, when known, the person's
homepage (read by the LLM). The person's library papers are checked against the
authorships of those works, which both picks the right OpenAlex profile and flags
papers that are probably attributed to the wrong person (homonyms, bad merges).
"""

import json
import logging
import re
import time
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from difflib import SequenceMatcher
from functools import lru_cache
from html.parser import HTMLParser
from io import BytesIO
from urllib.parse import urljoin

import httpx

from config import settings

log = logging.getLogger(__name__)

_OPENALEX = "https://api.openalex.org"
_ORCID = "https://pub.orcid.org/v3.0"
_MAILTO = "papermanager@local"
_MAX_CHECKED_PAPERS = 40


def _ssl():
    if settings.ssl_ca_bundle:
        return settings.ssl_ca_bundle
    return settings.ssl_verify


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_json(url: str, params: dict | None = None, headers: dict | None = None) -> dict | None:
    for attempt in range(3):
        try:
            r = httpx.get(url, params=params, headers=headers, verify=_ssl(), timeout=20,
                          follow_redirects=True)
        except httpx.HTTPError as exc:
            log.debug("CV fetch error | %s | %s", url, exc)
            time.sleep(2)
            continue
        if r.status_code == 429:
            time.sleep(5 * (attempt + 1))
            continue
        if r.status_code != 200:
            return None
        try:
            return r.json()
        except ValueError:
            return None
    return None


def _openalex(path: str, **params) -> dict | None:
    return _get_json(f"{_OPENALEX}{path}", params={**params, "mailto": _MAILTO})


# ── Names and titles ──────────────────────────────────────────────────────────

def _fold(s: str | None) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z\s-]", " ", s).replace("-", " ")


_NICKNAMES = [
    {"tom", "thomas"}, {"bob", "rob", "robert"}, {"bill", "will", "william"}, {"jim", "james"},
    {"mike", "michael"}, {"dave", "david"}, {"chris", "christopher", "christian"}, {"alex", "alexander", "alexandre"},
    {"ben", "benjamin"}, {"dan", "daniel"}, {"matt", "matthew"}, {"nick", "nicholas", "nicolas"},
    {"geoff", "geoffrey"}, {"steve", "stephen", "steven"}, {"andy", "andrew"}, {"sam", "samuel"},
    {"tony", "anthony"}, {"joe", "joseph"}, {"ed", "edward"}, {"jon", "jonathan"}, {"max", "maximilian"},
]


def _name_words(name: str | None) -> list[str]:
    name = name or ""
    if "," in name:  # "Doe, Jane" -> "Jane Doe"
        last, _, first = name.partition(",")
        name = f"{first} {last}"
    return _fold(name).split()


def same_person_name(a: str | None, b: str | None) -> bool:
    """Same surname and compatible given names ("C. P. Robert" ~ "Christian P. Robert", "Tom" ~ "Thomas")."""
    wa, wb = _name_words(a), _name_words(b)
    if not wa or not wb or wa[-1] != wb[-1]:
        return False
    ga, gb = wa[:-1], wb[:-1]
    if not ga or not gb:
        return True
    x, y = ga[0], gb[0]
    if "".join(ga) == "".join(gb):  # "Ya-Nan" ~ "Yanan"
        return True
    if x == y or any(x in n and y in n for n in _NICKNAMES):
        return True
    return (len(x) == 1 or len(y) == 1) and x[0] == y[0]


def _norm_title(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _fold(s)).strip()


def _same_title(a: str | None, b: str | None) -> bool:
    return SequenceMatcher(None, _norm_title(a), _norm_title(b)).ratio() >= 0.9


def _openalex_doi(doi: str | None) -> str | None:
    """Library DOI (or "arXiv:2501.01234") -> DOI as OpenAlex indexes it."""
    if not doi:
        return None
    d = doi.strip().lower()
    d = re.sub(r"^https?://(dx\.)?doi\.org/", "", d)
    m = re.match(r"^arxiv:(\d{4}\.\d{4,5})", d) or re.match(r"^(\d{4}\.\d{4,5})(v\d+)?$", d)
    if m:
        return f"10.48550/arxiv.{m.group(1)}"
    return d if d.startswith("10.") else None


# ── OpenAlex ──────────────────────────────────────────────────────────────────

@lru_cache(maxsize=4096)
def _work_authorships(doi: str) -> tuple:
    """(author_id, display_name, raw_name) for each author of a work; cached across people."""
    w = _openalex(f"/works/doi:{doi}", select="id,authorships")
    if not w:
        return ()
    return tuple(
        ((a.get("author") or {}).get("id"), (a.get("author") or {}).get("display_name"),
         a.get("raw_author_name"))
        for a in w.get("authorships") or []
    )


@lru_cache(maxsize=256)
def _author_works(author_id: str, limit: int = 600) -> tuple:
    works, cursor = [], "*"
    while cursor and len(works) < limit:
        page = _openalex("/works", filter=f"author.id:{author_id}", select="id,doi,title,publication_year,cited_by_count",
                         **{"per-page": 200, "cursor": cursor})
        if not page:
            break
        works += page.get("results") or []
        cursor = (page.get("meta") or {}).get("next_cursor")
    return tuple(works)


def _short_id(openalex_url: str | None) -> str | None:
    return openalex_url.rsplit("/", 1)[-1] if openalex_url else None


def _check_papers(name: str, papers: list[dict]) -> tuple[list[dict], Counter]:
    """Look for the person among each library paper's authors.

    Returns per-paper verdicts and the votes for each OpenAlex author id.
    """
    verdicts, votes = [], Counter()
    for p in papers[:_MAX_CHECKED_PAPERS]:
        doi = _openalex_doi(p.get("doi"))
        authorships = _work_authorships(doi) if doi else ()
        if not authorships:
            verdicts.append({**p, "verdict": "unknown"})
            continue
        ids = [aid for aid, dn, raw in authorships if same_person_name(name, dn) or same_person_name(name, raw)]
        if ids:
            votes.update(i for i in ids if i)
            verdicts.append({**p, "verdict": "author", "openalex_ids": [_short_id(i) for i in ids if i]})
        else:
            verdicts.append({**p, "verdict": "absent",
                             "listed_authors": [dn or raw for _, dn, raw in authorships][:12]})
    return verdicts, votes


def _resolve_author(person: dict, votes: Counter, papers: list[dict]) -> tuple[str | None, str]:
    if person.get("openalex_id"):
        return person["openalex_id"], "stored"
    if votes:
        return _short_id(votes.most_common(1)[0][0]), "papers"
    # No authorship to anchor on: a namesake is accepted only if one of the
    # person's library papers is among its works (common names have many homonyms).
    res = _openalex("/authors", search=person.get("name", ""), **{"per-page": 5}) or {}
    for a in res.get("results") or []:
        if not same_person_name(person.get("name"), a.get("display_name")):
            continue
        titles = [w.get("title") for w in _author_works(_short_id(a["id"]))]
        if any(_same_title(p["title"], t) for p in papers for t in titles):
            return _short_id(a["id"]), "name+title"
    return None, "not-found"


# ── ORCID ─────────────────────────────────────────────────────────────────────

def _orcid_date(d: dict | None) -> str | None:
    if not d:
        return None
    y = (d.get("year") or {}).get("value")
    m = (d.get("month") or {}).get("value")
    return f"{y}-{m}" if y and m else y


def _orcid_items(groups: list, key: str) -> list[dict]:
    items = []
    for grp in groups or []:
        for s in grp.get("summaries") or []:
            e = s.get(key) or {}
            org = e.get("organization") or {}
            addr = org.get("address") or {}
            items.append({
                "role": e.get("role-title"),
                "department": e.get("department-name"),
                "organization": org.get("name"),
                "place": ", ".join(x for x in (addr.get("city"), addr.get("country")) if x) or None,
                "start": _orcid_date(e.get("start-date")),
                "end": _orcid_date(e.get("end-date")),
                "source": "ORCID",
            })
    return sorted(items, key=lambda x: x.get("start") or "", reverse=True)


def fetch_orcid_cv(orcid_id: str) -> dict:
    data = _get_json(f"{_ORCID}/{orcid_id}/record", headers={"Accept": "application/json"})
    if not data:
        return {}
    person = data.get("person") or {}
    acts = data.get("activities-summary") or {}
    name = person.get("name") or {}
    urls = [
        {"name": u.get("url-name"), "url": (u.get("url") or {}).get("value")}
        for u in (person.get("researcher-urls") or {}).get("researcher-url") or []
    ]
    dois, titles = set(), []
    for grp in (acts.get("works") or {}).get("group") or []:
        for ws in grp.get("work-summary") or []:
            titles.append(((ws.get("title") or {}).get("title") or {}).get("value"))
            for ext in (ws.get("external-ids") or {}).get("external-id") or []:
                if ext.get("external-id-type") == "doi" and ext.get("external-id-value"):
                    dois.add(_openalex_doi(ext["external-id-value"]))
    return {
        "work_dois": dois,
        "work_titles": [t for t in titles if t],
        "name": " ".join(x for x in ((name.get("given-names") or {}).get("value"),
                                     (name.get("family-name") or {}).get("value")) if x),
        "biography": ((person.get("biography") or {}).get("content") or "").strip() or None,
        "urls": [u for u in urls if u["url"]],
        "employments": _orcid_items((acts.get("employments") or {}).get("affiliation-group"), "employment-summary"),
        "educations": _orcid_items((acts.get("educations") or {}).get("affiliation-group"), "education-summary"),
    }


# ── Homepage ──────────────────────────────────────────────────────────────────

class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.images, self._skip = [], [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self._skip += 1
        if tag == "img":
            a = dict(attrs)
            if a.get("src"):
                self.images.append((a["src"], a.get("alt") or ""))

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip and data.strip():
            self.parts.append(data.strip())


_HOMEPAGE_PROMPT = """Below is the text of a web page that may be the homepage or CV of the researcher {name}.
If the page is not about this researcher, return {{"about_person": false}}.
Otherwise extract their academic CV. Return ONLY JSON:
{{"about_person": true,
  "current_position": "e.g. Associate Professor of Statistics, University of Oxford",
  "positions": [{{"role": "...", "organization": "...", "start": "YYYY", "end": "YYYY or null"}}],
  "education": [{{"role": "PhD in Statistics", "organization": "...", "end": "YYYY"}}],
  "bio": "1-2 sentence research summary"}}
Only include facts stated on the page.

Page text:
{text}"""


def scrape_homepage_cv(url: str, name: str) -> dict:
    """Read a homepage with the LLM; returns {} if unreachable or not about this person."""
    try:
        r = httpx.get(url, verify=_ssl(), timeout=20, follow_redirects=True,
                      headers={"User-Agent": "Mozilla/5.0 (PaperManager CV)"})
        if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
            return {}
        parser = _Text()
        parser.feed(r.text)
        text = re.sub(r"\s+", " ", " ".join(parser.parts))[:9000]
        if len(text) < 200:
            return {}
        from services.litellm_client import chat_completion
        raw = chat_completion(messages=[{"role": "user", "content": _HOMEPAGE_PROMPT.format(name=name, text=text)}],
                              json_mode=True, max_tokens=1500, timeout=90)
        data = json.loads(re.search(r"\{.*\}", raw, re.S).group())
    except Exception as exc:
        log.debug("Homepage CV scrape failed | %s | %s", url, exc)
        return {}
    if not data.get("about_person"):
        return {}
    surname = (_name_words(name) or [""])[-1]
    for src, alt in parser.images:
        hay = _fold(f"{src} {alt}")
        if (surname and surname in hay) or re.search(r"photo|portrait|headshot|profile|\bme\b", hay):
            data["photo_url"] = urljoin(str(r.url), src)
            break
    for item in (data.get("positions") or []) + (data.get("education") or []):
        item["source"] = "homepage"
    return data


def _pick_homepage(urls: list[dict]) -> str | None:
    skip = ("linkedin", "twitter", "x.com", "github", "scholar.google", "researchgate", "orcid", "scopus",
            "dblp", "facebook", "mathgenealogy", "genealogy", "wikipedia")
    for u in urls:
        if not any(s in u["url"].lower() for s in skip):
            return u["url"]
    return None


# ── Wikidata and photo ────────────────────────────────────────────────────────

def fetch_wikidata(openalex_id: str | None, orcid_id: str | None) -> dict:
    """Portrait and website of the Wikidata item carrying this OpenAlex id or ORCID (exact id match only)."""
    keys = [f'?item wdt:P10283 "{openalex_id}"'] if openalex_id else []
    keys += [f'?item wdt:P496 "{orcid_id}"'] if orcid_id else []
    if not keys:
        return {}
    query = ("SELECT ?item ?image ?site WHERE { { " + " } UNION { ".join(keys) + " } "
             "OPTIONAL { ?item wdt:P18 ?image } OPTIONAL { ?item wdt:P856 ?site } } LIMIT 1")
    data = _get_json("https://query.wikidata.org/sparql", params={"query": query, "format": "json"},
                     headers={"User-Agent": "PaperManager/1.0 (https://github.com/NiklasAbraham/PaperManager; researcher CV)"})
    rows = ((data or {}).get("results") or {}).get("bindings") or []
    if not rows:
        return {}
    row = rows[0]
    return {"wikidata": row["item"]["value"], "image": (row.get("image") or {}).get("value"),
            "website": (row.get("site") or {}).get("value")}


def fetch_photo(url: str) -> str | None:
    """Download a portrait and return it as a small JPEG data URI."""
    try:
        from PIL import Image
        r = httpx.get(url, verify=_ssl(), timeout=20, follow_redirects=True,
                      headers={"User-Agent": "PaperManager/1.0 (https://github.com/NiklasAbraham/PaperManager; researcher CV)"})
        if r.status_code != 200:
            return None
        img = Image.open(BytesIO(r.content)).convert("RGB")
        if min(img.size) < 48:
            return None  # icons and spacers, not portraits
        img.thumbnail((256, 256))
        out = BytesIO()
        img.save(out, "JPEG", quality=82)
    except Exception as exc:
        log.debug("Photo fetch failed | %s | %s", url, exc)
        return None
    import base64
    return "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode()


# ── Build ─────────────────────────────────────────────────────────────────────

def _library_papers(driver, person_id: str) -> list[dict]:
    with driver.session() as s:
        return s.run(
            "MATCH (paper:Paper)-[:AUTHORED_BY]->(:Person {id: $id}) "
            "RETURN paper.id AS id, paper.title AS title, paper.doi AS doi, paper.year AS year "
            "ORDER BY paper.year DESC",
            id=person_id,
        ).data()


def _years(a: dict) -> str:
    ys = sorted(a.get("years") or [])
    if not ys:
        return ""
    return str(ys[0]) if ys[0] == ys[-1] else f"{ys[0]}–{ys[-1]}"


def build_person_cv(driver, person_id: str, scrape_homepage: bool = True) -> dict:
    """Refresh a person's CV, store it on the Person node and return it."""
    from db.queries.people import get_person

    person = get_person(driver, person_id)
    if not person:
        raise ValueError(f"Person {person_id} not found")
    name = person.get("name", "")
    papers = _library_papers(driver, person_id)

    verdicts, votes = _check_papers(name, papers)
    author_id, how = _resolve_author(person, votes, papers)
    author = _openalex(f"/authors/{author_id}") if author_id else None
    works = _author_works(author_id) if author else []

    # Library papers without a DOI: look for them in the author's works by title.
    work_titles = [w.get("title") for w in works]
    for v in verdicts:
        if v["verdict"] == "unknown" and any(_same_title(v["title"], t) for t in work_titles):
            v["verdict"] = "author"

    orcid_url = (author or {}).get("orcid") or person.get("orcid_url")
    m = re.search(r"(\d{4}-\d{4}-\d{4}-\d{3}[\dX])", orcid_url or "")
    orcid = fetch_orcid_cv(m.group(1)) if m else {}
    if orcid and orcid.get("name") and not same_person_name(name, orcid["name"]):
        orcid = {}  # ORCID record of someone else
    if orcid and orcid["work_titles"] and not any(
            _openalex_doi(p.get("doi")) in orcid["work_dois"]
            or any(_same_title(p["title"], t) for t in orcid["work_titles"]) for p in papers):
        orcid = {}  # lists works, none of them ours: a homonym merged into the OpenAlex profile

    wiki = fetch_wikidata(author_id if author else None, m.group(1) if (m and orcid) else None)
    homepage = person.get("website_url") or _pick_homepage(orcid.get("urls") or []) or wiki.get("website")
    page = scrape_homepage_cv(homepage, name) if (homepage and scrape_homepage) else {}

    checked = [v for v in verdicts if v["verdict"] != "unknown"]
    absent = [v for v in verdicts if v["verdict"] == "absent"]
    if not papers:
        status = "no-papers"
    elif not author:
        status = "not-found"
    elif absent and len(absent) * 2 >= len(checked):
        status = "mismatch"
    elif absent:
        status = "partial"
    else:
        status = "ok"

    summary = (author or {}).get("summary_stats") or {}
    last_inst = [i.get("display_name") for i in (author or {}).get("last_known_institutions") or []]
    current = (page.get("current_position")
               or next((f"{e['role'] + ', ' if e.get('role') else ''}{e['organization']}"
                        for e in orcid.get("employments") or [] if not e.get("end") and e.get("organization")), None)
               or (last_inst[0] if last_inst else None))

    cv = {
        "updated_at": _now(),
        "name": (author or {}).get("display_name") or name,
        "current_position": current,
        "positions": (page.get("positions") or []) + (orcid.get("employments") or []),
        "education": (page.get("education") or []) + (orcid.get("educations") or []),
        "affiliation_history": [
            {"institution": (a.get("institution") or {}).get("display_name"), "years": _years(a)}
            for a in (author or {}).get("affiliations") or []
        ][:12],
        "metrics": {
            "works": (author or {}).get("works_count"),
            "citations": (author or {}).get("cited_by_count"),
            "h_index": summary.get("h_index"),
            "i10_index": summary.get("i10_index"),
        },
        "topics": [t.get("display_name") for t in (author or {}).get("topics") or []][:10],
        "top_works": [
            {"title": w.get("title"), "year": w.get("publication_year"), "citations": w.get("cited_by_count"),
             "doi": (w.get("doi") or "").replace("https://doi.org/", "") or None}
            for w in sorted(works, key=lambda w: w.get("cited_by_count") or 0, reverse=True)[:8]
        ],
        "bio": page.get("bio") or orcid.get("biography"),
        "sources": {
            "openalex": f"https://openalex.org/{author_id}" if author else None,
            "orcid": f"https://orcid.org/{m.group(1)}" if orcid and m else None,
            "homepage": homepage if page else None,
            "wikidata": wiki.get("wikidata"),
        },
        "check": {
            "status": status,
            "resolved_by": how,
            "library_papers": len(papers),
            "confirmed": sum(1 for v in verdicts if v["verdict"] == "author"),
            "unverifiable": sum(1 for v in verdicts if v["verdict"] == "unknown"),
            "absent": [{"id": v["id"], "title": v["title"], "listed_authors": v["listed_authors"]} for v in absent],
            "other_openalex_profiles": sorted({i for v in verdicts for i in v.get("openalex_ids", [])} - {author_id}),
        },
    }

    props = {"cv": json.dumps(cv, ensure_ascii=False), "cv_status": status, "cv_updated_at": cv["updated_at"]}
    # Only trust the profile for the person's own fields when the papers agree with it.
    if author and status in ("ok", "partial"):
        props.update({"openalex_id": author_id, "citation_count": author.get("cited_by_count"),
                      "h_index": summary.get("h_index")})
        if current:
            props["affiliation"] = current
        if not person.get("orcid_url") and cv["sources"]["orcid"]:
            props["orcid_url"] = cv["sources"]["orcid"]
        if not person.get("website_url") and homepage and page:
            props["website_url"] = homepage
        if not person.get("bio") and cv["bio"]:
            props["bio"] = cv["bio"]
        if (not person.get("skills") or person.get("skills") == "[]") and cv["topics"]:
            props["skills"] = json.dumps(cv["topics"][:6], ensure_ascii=False)
        photo_src = wiki.get("image") or page.get("photo_url")
        if photo_src and not person.get("photo"):
            props["photo"] = fetch_photo(photo_src)
            props["photo_source"] = photo_src if props["photo"] else None
    with driver.session() as s:
        s.run("MATCH (p:Person {id: $id}) SET p += $props",
              id=person_id, props={k: v for k, v in props.items() if v is not None})
    log.info("CV built | person=%s | status=%s | author=%s", name, status, author_id)
    return cv


def build_all_cvs(driver, only_missing: bool = True, pause: float = 0.0) -> dict:
    """Build CVs one person at a time, authors with the most library papers first.

    ``pause`` seconds between people keeps the load on OpenAlex, ORCID and the LLM low;
    with ``only_missing`` an interrupted run picks up where it stopped.
    """
    with driver.session() as s:
        ids = [r["id"] for r in s.run(
            "MATCH (p:Person) WHERE ()-[:AUTHORED_BY]->(p) "
            + ("AND p.cv_updated_at IS NULL " if only_missing else "")
            + "RETURN p.id AS id ORDER BY COUNT { (:Paper)-[:AUTHORED_BY]->(p) } DESC"
        )]
    counts = Counter()
    for n, pid in enumerate(ids, 1):
        try:
            counts[build_person_cv(driver, pid)["check"]["status"]] += 1
        except Exception as exc:
            log.warning("CV build failed | person=%s | %s", pid, exc)
            counts["error"] += 1
        if n % 25 == 0 or n == len(ids):
            log.info("CV build progress | %d/%d | %s", n, len(ids), dict(counts))
        if pause and n < len(ids):
            time.sleep(pause)
    return dict(counts)
