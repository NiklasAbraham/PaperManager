"""Conference explorer tools: who publishes on a topic at NeurIPS / ICML / ICLR / CVPR /
ACL / ... (one conference or all loaded ones), what one institution published there, and
papers and authors across every loaded conference. Read-only; they use the datasets the
backend has built (services/conferences/) and never call a language model."""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from services.conferences import areas, catalog, store


def _library() -> dict:
    """Folded title -> library paper id, for library_paper_id on returned papers."""
    try:
        from routers.conferences import library_titles

        return library_titles()
    except Exception:  # noqa: BLE001 — the tools work without the library match
        return {}


def _ready(conference: str):
    ed = catalog.resolve(conference)
    if ed is None:
        return None, {"error": f"Unknown conference '{conference}'. Call list_conferences for the keys."}
    ds = store.load(ed.key)
    if ds is None:
        st = store.status(ed.key)
        return None, {"error": f"{ed.name} is not loaded (state: {st.get('state')}). "
                               "Open it in the app's Conferences page, or call list_conferences."}
    return ds, None


def _paper(p: dict) -> dict:
    names = [a["short"] for a in areas.AREAS]
    out = {
        "title": p["title"], "decision": p["decision"],
        "area": names[p["area"]] if p.get("area", -1) >= 0 else None,
        "institutions": [i["name"] for i in p["institutions"]],
        "url": p.get("url") or p.get("forum") or None,
    }
    if p.get("match") is not None:
        out["match"] = p["match"]
    if p.get("library_id"):
        out["library_paper_id"] = p["library_id"]
    if p.get("conf_name"):
        out = {"conference": p["conf_name"], **out}
    return out


def _topic_all(query: str, k: int, papers: int) -> dict:
    from services.conferences import search

    try:
        res = search.topic(query, k=max(50, min(int(k), 2000)) if k != 100 else 300, library=_library(),
                           paper_top=max(1, min(int(papers), 40)), per_conference=0)
    except RuntimeError as exc:
        return {"error": str(exc)}
    mix = sorted((a for a in res["areas"] if a["count"]), key=lambda a: -a["count"])
    return {
        "conference": "all loaded conferences", "query": query,
        "closest_papers_pooled": res["k"], "similarity_threshold": res["threshold"], "of_papers": res["total"],
        "per_conference": [{"conference": c["name"], "papers_close": c["count"], "per_1000_papers": c["per_1k"],
                            "conference_size": c["papers"]} for c in res["conferences"]],
        "trend": [{"series": t["series"], "per_1000_papers_by_year": {str(p["year"]): p["per_1k"] for p in t["points"]}}
                  for t in res["trend"]],
        "not_searched": [{"conference": c["name"], "reason": c["reason"]} for c in res["skipped"]],
        "with_company_author": res["with_industry"], "with_known_institution": res["with_institution"],
        "areas": [{"area": a["name"], "papers": a["count"]} for a in mix[:8]],
        "universities_and_institutes": [{"name": x["name"], "papers": x["count"],
                                         "by_conference": {c["key"]: c["count"] for c in x["conferences"]}}
                                        for x in res["academia"]],
        "companies": [{"name": x["name"], "papers": x["count"],
                       "by_conference": {c["key"]: c["count"] for c in x["conferences"]}} for x in res["industry"]],
        "papers": [_paper(p) for p in res["papers"]],
    }


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def list_conferences(only_loaded: bool = True) -> dict:
        """Conference-years the explorer knows (NeurIPS, ICML, ICLR, CVPR, ICCV, ECCV, ACL,
        EMNLP, AAAI, CoRL, ...) with key (e.g. "neurips2026"), state and paper count.
        only_loaded=False also lists the ones not downloaded yet."""
        rows = store.catalog_rows()
        if only_loaded:
            rows = [r for r in rows if r["state"] in ("ready", "partial", "embedding")]
        return {"conferences": [{k: r[k] for k in ("key", "name", "state", "papers", "institutions")}
                                for r in rows]}

    @mcp.tool()
    def conference_topic(conference: str, query: str, k: int = 100, papers: int = 15) -> dict:
        """Who publishes on a topic at one conference, or at all of them. `conference`: a
        key or name ("neurips2026", "ICML 2025", "iclr" = latest) or "all"; `query`: a topic
        or a pasted abstract. One conference: the k papers closest to the query (title +
        abstract embeddings) counted per institution (universities, companies), research-area
        mix, closest papers. "all": the k (default 300) closest pooled over every loaded
        conference (title-only embeddings), per conference per 1,000 of its papers, the
        per-year trend of series loaded for several years, institutions pooled. Papers
        already in the library carry library_paper_id."""
        if conference.strip().lower() in ("all", "*", "any", "every"):
            return _topic_all(query, k, papers)
        ds, err = _ready(conference)
        if err:
            return err
        res = store.topic(ds, query, k=k, paper_top=max(1, min(int(papers), 40)), library=_library())
        mix = sorted((a for a in res["areas"] if a["count"]), key=lambda a: -a["count"])
        return {
            "conference": ds.raw["name"], "query": query, "mode": res["mode"],
            "closest_papers_considered": res["k"], "of_papers": res["total"],
            "with_company_author": res["with_industry"],
            "areas": [{"area": a["name"], "papers": a["count"]} for a in mix[:8]],
            "universities_and_institutes": [{"name": x["name"], "papers": x["count"],
                                             "share_of_their_papers": x["of_own"]} for x in res["academia"]],
            "companies": [{"name": x["name"], "papers": x["count"],
                           "share_of_their_papers": x["of_own"]} for x in res["industry"]],
            "papers": [_paper(p) for p in res["papers"]],
        }

    @mcp.tool()
    def conference_institution(conference: str, institution: str, papers: int = 40) -> dict:
        """What one institution published at a conference: rank, paper count (full and
        fractional), research-area mix against the whole conference, main collaborators,
        most frequent authors and its papers. `institution` is matched by name
        ("MIT", "Google", "Tsinghua")."""
        ds, err = _ready(conference)
        if err:
            return err
        hits = store.search_institutions(ds, q=institution, limit=5)["rows"]
        if not hits:
            return {"error": f"No institution matching '{institution}' at {ds.raw['name']}."}
        d = store.institution_detail(ds, hits[0]["slug"])
        total = sum(a["count"] for a in d["conference_areas"]) or 1
        mix = sorted((a for a in d["areas"] if a["count"]), key=lambda a: -a["count"])
        conf = {a["index"]: a["count"] for a in d["conference_areas"]}
        return {
            "conference": ds.raw["name"], "institution": d["name"],
            "other_matches": [h["name"] for h in hits[1:]],
            "sector": "industry" if d["sector"] == "I" else "academia",
            "rank": d["rank"], "papers": d["papers"], "fractional_papers": d["fractional"],
            "areas": [{"area": a["name"], "papers": a["count"],
                       "conference_share": round(conf[a["index"]] / total, 3)} for a in mix[:10]],
            "collaborators": [{"name": c["name"], "shared_papers": c["shared"]} for c in d["collaborators"][:8]],
            "authors": d["authors"][:10],
            "paper_list": [_paper(p) for p in d["paper_list"][:max(1, min(int(papers), 100))]],
        }

    @mcp.tool()
    def conference_search_papers(query: str, limit: int = 20, series: str = "", year_min: int = 0,
                                 year_max: int = 0) -> dict:
        """Find papers across every loaded conference by title or meaning (`query`: a
        title, part of one or a few words; typos tolerated). Title matches first (exact,
        prefix, phrase, words, most words), then the closest in meaning; each with
        conference, decision, area, institutions, url, match (cosine) and library_paper_id.
        `series`: comma list ("neurips,icml"); year_min / year_max."""
        from services.conferences import search

        res = search.search_papers(query, limit=max(1, min(int(limit), 50)), series=series,
                                   year_min=year_min or None, year_max=year_max or None, library=_library())

        def row(p: dict) -> dict:
            out = _paper(p)
            if p.get("title_match"):
                out["title_match"] = p["title_match"]
            return out

        return {
            "query": query, "conferences_searched": [c["name"] for c in res["conferences"]],
            "title_matches": [row(p) for p in res["title"]], "title_match_total": res["title_total"],
            "closest_by_meaning": [row(p) for p in res["semantic"]],
        }

    @mcp.tool()
    def conference_search_author(name: str, limit: int = 10, papers: int = 30) -> dict:
        """Find an author across every loaded conference: full name, surname, "Surname,
        First", initials ("c deane") or a prefix; one typo tolerated. Names are grouped by
        spelling (accents, case folded), so one name can be two people: each author lists
        the institutions on their papers and, when the papers split into groups sharing no
        institution and no co-author, `possible_identities`. Papers per conference, with the
        author's institutions on each."""
        from services.conferences import search

        res = search.search_authors(name, limit=max(1, min(int(limit), 30)), library=_library())
        cap = max(1, min(int(papers), 100))
        out = []
        for a in res["authors"]:
            listed = []
            for c in a["conferences"]:
                for p in c["papers_by_author"]:
                    if len(listed) >= cap:
                        break
                    listed.append({**_paper(p), "conference": c["name"],
                                   "author_institutions": p["author_institutions"]})
            out.append({
                "name": a["name"], "match_score": a["score"], "papers": a["papers"],
                "conferences": {c["name"]: len(c["papers_by_author"]) for c in a["conferences"]},
                "coauthors": a["coauthors"],
                "institutions": [{"name": i["name"], "papers": i["papers"]} for i in a["institutions"]],
                "possible_identities": [{"papers": g["papers"], "institutions": g["institutions"],
                                         "conferences": g["conferences"]} for g in a["identities"]],
                "paper_list": listed,
            })
        return {"query": name, "matches": res["total"], "authors": out}
