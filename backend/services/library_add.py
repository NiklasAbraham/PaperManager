"""Batch add: put a list of cited papers into the library and into one project, in one call.

Backs the MCP tool `library_add` (tools/library_tools.py). A client that has written a
report's reference list (a `papers.json`, or the same entries inline) used to call
`library_lookup`, then `add_paper_metadata` per missing paper, then `add_to_project` per
paper: about two calls per paper. This does the same in one call and a fixed number of
Cypher queries:

1. resolve the project (id or name, case-insensitive, visible to the user);
2. confirm the `paperId`s the entries already carry;
3. `library_lookup` on the rest (DOI first, then title; services/library_lookup.py);
4. create the papers that are still missing (metadata only, `metadata_source: manual`),
   with their authors when the entry gives them as a list of full names;
5. link every paper to the project (MERGE, so existing links are kept and counted).

Entries are deduplicated within the batch on the same DOI / title keys the lookup uses, so
a paper cited twice is created once. With a `path`, the file is rewritten with each entry's
`paperId`, `url` and `status` (`present` = was in the library, `added` = created now), which
is the `papers.json` contract of the desk reports. `dry_run` reports what would happen and
writes nothing.
"""
from __future__ import annotations

import json
import os

from neo4j import Driver

from db.queries.papers import create_paper
from db.queries.people import get_or_create_person, link_author
from db.queries.visibility import paper_visibility_clause, project_visibility_clause
from services.library_lookup import MAX_ITEMS, doi_key, lookup, title_key

_FIELDS = ("year", "venue", "abstract", "document_type", "published_date")


def _doi(e: dict) -> str:
    """The entry's DOI, or the arXiv DOI built from its `arxiv` id."""
    if e.get("doi"):
        return str(e["doi"]).strip()
    ax = str(e.get("arxiv") or "").strip()
    if not ax:
        return ""
    ax = ax.removeprefix("arXiv:").removeprefix("arxiv:")
    return f"10.48550/arXiv.{ax}"


def _year(v) -> int | None:
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def batch_key(e: dict) -> str | None:
    """Same-paper key inside one batch: the DOI key, else the title key."""
    return doi_key(_doi(e)) or (("t:" + title_key(e.get("title"))) if title_key(e.get("title")) else None)


def load_items(items: list[dict] | None, path: str) -> tuple[list[dict], dict | None, str | None]:
    """(entries, wrapper, error). A file may hold a list or {"papers": [...]}; the wrapper is
    kept so the file is written back in the same shape."""
    if path:
        if not os.path.isabs(path):
            return [], None, f"path must be absolute: {path}"
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as exc:
            return [], None, f"cannot read {path}: {exc}"
        if isinstance(data, dict) and isinstance(data.get("papers"), list):
            return data["papers"], data, None
        if isinstance(data, list):
            return data, None, None
        return [], None, f"{path} holds neither a list nor {{\"papers\": [...]}}"
    return list(items or []), None, None


def add(driver: Driver, items: list[dict] | None = None, project: str = "", path: str = "",
        dry_run: bool = False, url_base: str = "") -> dict:
    """Run the batch add. Returns counts and one short row per entry (see module doc)."""
    entries, wrapper, err = load_items(items, path)
    if err:
        return {"error": err}
    if not entries:
        return {"error": "give `papers` (a list of entries) or `path` (a papers.json)"}
    if len(entries) > MAX_ITEMS:
        return {"error": f"{len(entries)} entries; at most {MAX_ITEMS} per call"}
    bad = [i for i, e in enumerate(entries) if not isinstance(e, dict) or not str(e.get("title") or "").strip()]
    if bad:
        return {"error": f"entries without a title: {bad[:20]}"}
    url = lambda pid: f"{url_base.rstrip('/')}/paper/{pid}"  # noqa: E731

    project = (project or "").strip()
    proj = None
    vis, vis_params = paper_visibility_clause("p")
    pvis, pvis_params = project_visibility_clause("pr")
    with driver.session() as s:
        if project:
            r = s.run(f"""MATCH (pr:Project) WHERE (pr.id = $q OR toLower(pr.name) = toLower($q)) AND {pvis}
                          RETURN pr.id AS id, pr.name AS name ORDER BY pr.id = $q DESC LIMIT 1""",
                      q=project, **pvis_params).single()
            if not r:
                return {"error": f"no project named or with id '{project}' (create_project first)"}
            proj = {"id": r["id"], "name": r["name"]}
        given = sorted({str(e["paperId"]) for e in entries if e.get("paperId")})
        known = set()
        if given:
            known = {r["id"] for r in s.run(
                f"UNWIND $ids AS id MATCH (p:Paper {{id: id}}) WHERE {vis} RETURN p.id AS id",
                ids=given, **vis_params)}

    # One row per entry: (status, paper id, kind). Entries naming the same paper share a row.
    rows: list[dict] = [{} for _ in entries]
    first_of: dict[str, int] = {}
    todo: list[int] = []
    for i, e in enumerate(entries):
        k = batch_key(e)
        if k and k in first_of:
            rows[i] = {"same_as": first_of[k]}
            continue
        if k:
            first_of[k] = i
        if e.get("paperId") and str(e["paperId"]) in known:
            rows[i] = {"status": "present", "id": str(e["paperId"]), "kind": "id"}
        else:
            todo.append(i)

    if todo:
        found = lookup(driver, [_doi(entries[i]) for i in todo],
                       [str(entries[i]["title"]).strip() for i in todo])
        for i, item in zip(todo, found["items"]):
            m = item["match"]
            if m is None:
                rows[i] = {"status": "missing"}
                continue
            first = m if isinstance(m, dict) else m[0]
            rows[i] = {"status": "present", "id": first["id"], "kind": item["kind"]}
            if isinstance(m, list):
                rows[i]["duplicates"] = [x["id"] for x in m]

    authors_ignored = 0
    for i, row in enumerate(rows):
        if row.get("status") != "missing":
            continue
        e = entries[i]
        names = e.get("authors")
        if dry_run:
            row["status"] = "would_add"
            continue
        p = create_paper(driver, {"title": str(e["title"]).strip(), "doi": _doi(e) or None,
                                  **{f: e.get(f) for f in _FIELDS if f != "year"},
                                  "year": _year(e.get("year")), "metadata_source": "manual"})
        row.update(status="added", id=p["id"])
        if isinstance(names, list):
            for name in (str(n).strip() for n in names):
                if name:
                    link_author(driver, p["id"], get_or_create_person(driver, name)["id"])
        elif names:
            authors_ignored += 1

    for i, row in enumerate(rows):
        if "same_as" in row:
            rows[i] = {**rows[row["same_as"]], "same_as": row["same_as"]}

    linked = 0
    ids = sorted({r["id"] for r in rows if r.get("id")})
    if proj and ids:
        if dry_run:
            with driver.session() as s:
                inside = {r["id"] for r in s.run(
                    """UNWIND $ids AS id MATCH (p:Paper {id: id})-[:IN_PROJECT]->(:Project {id: $pr})
                       RETURN p.id AS id""", ids=ids, pr=proj["id"])}
            linked = len(set(ids) - inside)
        else:
            with driver.session() as s:
                linked = sum(not r["had"] for r in s.run(
                    """UNWIND $ids AS id MATCH (p:Paper {id: id}), (pr:Project {id: $pr})
                       WITH p, pr, EXISTS { (p)-[:IN_PROJECT]->(pr) } AS had
                       MERGE (p)-[:IN_PROJECT]->(pr)
                       RETURN had""", ids=ids, pr=proj["id"]))

    if path and not dry_run:
        for e, r in zip(entries, rows):
            if r.get("id"):
                e.update(paperId=r["id"], url=url(r["id"]),
                         status="added" if r["status"] == "added" else "present")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(wrapper if wrapper is not None else entries, f, indent=1, ensure_ascii=False)
            f.write("\n")

    out = []
    for i, (e, r) in enumerate(zip(entries, rows)):
        o = {"i": i, "title": str(e["title"])[:70], "status": r["status"]}
        for k in ("id", "kind", "same_as", "duplicates"):
            if k in r:
                o[k] = r[k]
        if r.get("id"):
            o["url"] = url(r["id"])
        out.append(o)
    count = lambda st: sum(1 for r in rows if r["status"] == st and "same_as" not in r)  # noqa: E731
    res = {"entries": len(entries), "present": count("present"),
           ("would_add" if dry_run else "added"): count("would_add" if dry_run else "added"),
           "same_in_batch": sum(1 for r in rows if "same_as" in r)}
    if proj:
        res["project"] = proj["name"]
        res["would_link" if dry_run else "linked"] = linked
    if path:
        res["path"] = path
        res["written"] = not dry_run
    if authors_ignored:
        res["note"] = (f"{authors_ignored} entries give `authors` as a string; authors are only "
                       "linked from a list of full names")
    if dry_run:
        res["dry_run"] = True
    res["items"] = out
    return res
