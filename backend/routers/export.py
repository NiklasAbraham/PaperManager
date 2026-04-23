import csv
import io
import json
import logging
import re
import zipfile
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from neo4j import Driver

from db.connection import get_driver

log = logging.getLogger(__name__)
router = APIRouter(prefix="/export", tags=["export"])

# ── Turtle helpers ────────────────────────────────────────────────────────────

PM   = "http://papermanager.local/ontology#"
PMR  = "http://papermanager.local/resource/"
XSD  = "http://www.w3.org/2001/XMLSchema#"

TURTLE_PREFIXES = """\
@prefix pm:  <http://papermanager.local/ontology#> .
@prefix pmr: <http://papermanager.local/resource/> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

"""


def _safe_uri(s: str) -> str:
    """Encode a string for use inside a URI."""
    return re.sub(r"[^A-Za-z0-9_\-]", lambda m: "%" + m.group().encode().hex().upper(), str(s))


def _lit(v) -> str:
    """Serialize a Python value as a Turtle literal."""
    if v is None:
        return None
    if isinstance(v, bool):
        return f'"{str(v).lower()}"^^xsd:boolean'
    if isinstance(v, int):
        return f'"{v}"^^xsd:integer'
    if isinstance(v, float):
        return f'"{v}"^^xsd:decimal'
    s = str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")
    return f'"{s}"'


def _node_turtle(uri: str, type_name: str, props: dict, skip: set | None = None) -> list[str]:
    """Build Turtle lines for a single node."""
    skip = skip or set()
    lines = [f"{uri} a pm:{type_name} ;"]
    pairs = []
    for k, v in props.items():
        if k in skip or v is None:
            continue
        lit = _lit(v)
        if lit:
            pairs.append(f'    pm:{k} {lit}')
    if pairs:
        lines.append(" ;\n".join(pairs) + " .")
    else:
        lines[-1] = lines[-1].rstrip(" ;") + " ."
    return lines


# ── BibTeX (existing) ─────────────────────────────────────────────────────────

@router.get("/bibtex")
def export_bibtex(driver: Driver = Depends(get_driver)):
    """Export all papers as a BibTeX .bib file."""
    papers = []
    with driver.session() as session:
        result = session.run(
            """
            MATCH (p:Paper)
            OPTIONAL MATCH (p)-[:AUTHORED_BY]->(person:Person)
            WITH p, collect(person.name) AS authors
            RETURN p, authors
            ORDER BY p.title
            """
        )
        for record in result:
            props = dict(record["p"])
            props["_authors"] = record["authors"]
            papers.append(props)

    lines: list[str] = []
    for p in papers:
        key = (p.get("id") or "unknown")[:8]
        title   = _bib_escape(p.get("title") or "")
        year    = p.get("year", "")
        doi     = p.get("doi") or ""
        authors = " and ".join(p.get("_authors") or [])

        lines.append(f"@article{{{key},")
        lines.append(f"  title  = {{{title}}},")
        if authors:
            lines.append(f"  author = {{{authors}}},")
        if year:
            lines.append(f"  year   = {{{year}}},")
        if doi:
            lines.append(f"  doi    = {{{doi}}},")
        lines.append("}")
        lines.append("")

    content = "\n".join(lines)
    return Response(
        content,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=papers.bib"},
    )


# ── RDF / Turtle export ───────────────────────────────────────────────────────

@router.get("/rdf")
def export_rdf(driver: Driver = Depends(get_driver)):
    """Export the entire graph as an RDF Turtle (.ttl) file."""
    out: list[str] = [TURTLE_PREFIXES]
    SKIP_INTERNAL = {"raw_text", "drive_file_id"}

    with driver.session() as session:

        # Papers
        for r in session.run("MATCH (p:Paper) RETURN p"):
            props = dict(r["p"])
            pid = props.get("id", "")
            uri = f"pmr:paper_{_safe_uri(pid)}"
            out += _node_turtle(uri, "Paper", props, skip=SKIP_INTERNAL)
            out.append("")

        # People
        for r in session.run("MATCH (p:Person) RETURN p"):
            props = dict(r["p"])
            pid = props.get("id", "")
            uri = f"pmr:person_{_safe_uri(pid)}"
            out += _node_turtle(uri, "Person", props)
            out.append("")

        # Tags
        for r in session.run("MATCH (t:Tag) RETURN t"):
            props = dict(r["t"])
            name = props.get("name", "")
            uri = f"pmr:tag_{_safe_uri(name)}"
            out.append(f'{uri} a pm:Tag ; pm:name {_lit(name)} .')
            out.append("")

        # Topics
        for r in session.run("MATCH (t:Topic) RETURN t"):
            props = dict(r["t"])
            name = props.get("name", "")
            uri = f"pmr:topic_{_safe_uri(name)}"
            out += _node_turtle(uri, "Topic", props)
            out.append("")

        # Projects
        for r in session.run("MATCH (p:Project) RETURN p"):
            props = dict(r["p"])
            pid = props.get("id", "")
            uri = f"pmr:project_{_safe_uri(pid)}"
            out += _node_turtle(uri, "Project", props)
            out.append("")

        # Notes (content only — mentions handled via edges)
        for r in session.run("MATCH (n:Note) RETURN n"):
            props = dict(r["n"])
            nid = props.get("id", "")
            uri = f"pmr:note_{_safe_uri(nid)}"
            out += _node_turtle(uri, "Note", props)
            out.append("")

        # ── Relationships ─────────────────────────────────────────────────────

        out.append("# --- Relationships ---\n")

        for r in session.run("MATCH (p:Paper)-[:AUTHORED_BY]->(a:Person) RETURN p.id AS pid, a.id AS aid"):
            out.append(f"pmr:paper_{_safe_uri(r['pid'])} pm:authoredBy pmr:person_{_safe_uri(r['aid'])} .")

        for r in session.run("MATCH (p:Paper)-[rel:INVOLVES]->(a:Person) RETURN p.id AS pid, a.id AS aid, rel.role AS role"):
            blank = f"pmr:involves_{_safe_uri(r['pid'])}_{_safe_uri(r['aid'])}"
            out.append(f"{blank} a pm:InvolvesRel ; pm:paper pmr:paper_{_safe_uri(r['pid'])} ; pm:person pmr:person_{_safe_uri(r['aid'])} ; pm:role {_lit(r['role'])} .")

        for r in session.run("MATCH (p:Paper)-[:TAGGED]->(t:Tag) RETURN p.id AS pid, t.name AS tname"):
            out.append(f"pmr:paper_{_safe_uri(r['pid'])} pm:taggedWith pmr:tag_{_safe_uri(r['tname'])} .")

        for r in session.run("MATCH (p:Paper)-[:ABOUT]->(t:Topic) RETURN p.id AS pid, t.name AS tname"):
            out.append(f"pmr:paper_{_safe_uri(r['pid'])} pm:about pmr:topic_{_safe_uri(r['tname'])} .")

        for r in session.run("MATCH (p:Paper)-[:CITES]->(ref:Paper) RETURN p.id AS pid, ref.id AS rid"):
            out.append(f"pmr:paper_{_safe_uri(r['pid'])} pm:cites pmr:paper_{_safe_uri(r['rid'])} .")

        for r in session.run("MATCH (p:Paper)-[:IN_PROJECT]->(proj:Project) RETURN p.id AS pid, proj.id AS projid"):
            out.append(f"pmr:paper_{_safe_uri(r['pid'])} pm:inProject pmr:project_{_safe_uri(r['projid'])} .")

        for r in session.run("MATCH (p:Paper)-[:HAS_NOTE]->(n:Note) RETURN p.id AS pid, n.id AS nid"):
            out.append(f"pmr:paper_{_safe_uri(r['pid'])} pm:hasNote pmr:note_{_safe_uri(r['nid'])} .")

        for r in session.run("MATCH (n:Note)-[:MENTIONS]->(x) RETURN n.id AS nid, labels(x) AS lbls, x.id AS xid, x.name AS xname"):
            lbl = (r["lbls"] or ["Unknown"])[0]
            if lbl == "Person":
                out.append(f"pmr:note_{_safe_uri(r['nid'])} pm:mentions pmr:person_{_safe_uri(r['xid'])} .")
            elif lbl == "Topic":
                out.append(f"pmr:note_{_safe_uri(r['nid'])} pm:mentions pmr:topic_{_safe_uri(r['xname'])} .")

        for r in session.run("MATCH (p:Person)-[:SPECIALIZES_IN]->(t:Topic) RETURN p.id AS pid, t.name AS tname"):
            out.append(f"pmr:person_{_safe_uri(r['pid'])} pm:specializesIn pmr:topic_{_safe_uri(r['tname'])} .")

    content = "\n".join(out)
    return Response(
        content,
        media_type="text/turtle; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=papermanager.ttl"},
    )


# ── CSV export (ZIP) ──────────────────────────────────────────────────────────

@router.get("/csv")
def export_csv(driver: Driver = Depends(get_driver)):
    """Export the entire graph as a ZIP of CSV files."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:

        with driver.session() as session:

            def _csv(rows: list[dict], filename: str):
                if not rows:
                    zf.writestr(filename, "")
                    return
                s = io.StringIO()
                w = csv.DictWriter(s, fieldnames=list(rows[0].keys()))
                w.writeheader()
                w.writerows(rows)
                zf.writestr(filename, s.getvalue())

            # Papers
            papers = [dict(r["p"]) for r in session.run("MATCH (p:Paper) RETURN p ORDER BY p.created_at DESC")]
            for p in papers:
                p.pop("raw_text", None)
            _csv(papers, "papers.csv")

            # People
            people = [dict(r["p"]) for r in session.run("MATCH (p:Person) RETURN p ORDER BY p.name")]
            _csv(people, "people.csv")

            # Tags
            tags = [dict(r["t"]) for r in session.run("MATCH (t:Tag) RETURN t ORDER BY t.name")]
            _csv(tags, "tags.csv")

            # Topics
            topics = [dict(r["t"]) for r in session.run("MATCH (t:Topic) RETURN t ORDER BY t.name")]
            _csv(topics, "topics.csv")

            # Projects
            projects = [dict(r["p"]) for r in session.run("MATCH (p:Project) RETURN p ORDER BY p.name")]
            _csv(projects, "projects.csv")

            # Notes
            notes = [dict(r["n"]) for r in session.run("MATCH (n:Note) RETURN n")]
            _csv(notes, "notes.csv")

            # Edges
            edges: list[dict] = []
            for r in session.run("MATCH (a)-[rel]->(b) RETURN a.id AS src, type(rel) AS type, b.id AS tgt, b.name AS tgt_name, properties(rel) AS props"):
                row = {
                    "source_id":   r["src"] or "",
                    "type":        r["type"],
                    "target_id":   r["tgt"] or r["tgt_name"] or "",
                    "extra":       json.dumps(dict(r["props"])) if r["props"] else "",
                }
                edges.append(row)
            _csv(edges, "edges.csv")

    buf.seek(0)
    return Response(
        buf.read(),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=papermanager_export.zip"},
    )


# ── RDF / Turtle import ───────────────────────────────────────────────────────

_TRIPLE_RE = re.compile(
    r'(pmr:\S+|"[^"]*"(?:\^\^xsd:\w+)?)\s+(pm:\w+|a)\s+(pmr:\S+|"[^"]*"(?:\^\^xsd:\w+)?)\s*\.'
)
_LIT_RE  = re.compile(r'^"(.*?)"(?:\^\^xsd:(\w+))?$', re.DOTALL)
_PMR_RE  = re.compile(r'^pmr:((\w+)_(.+))$')


def _parse_literal(tok: str):
    m = _LIT_RE.match(tok)
    if not m:
        return tok
    val, dtype = m.group(1), m.group(2)
    val = val.replace("\\n", "\n").replace("\\r", "\r").replace('\\"', '"').replace("\\\\", "\\")
    if dtype == "integer":
        try:
            return int(val)
        except ValueError:
            return val
    if dtype in ("decimal", "float"):
        try:
            return float(val)
        except ValueError:
            return val
    if dtype == "boolean":
        return val.lower() == "true"
    return val


def _parse_uri(tok: str) -> tuple[str, str, str] | None:
    """Return (full_local, node_type_prefix, local_id) or None."""
    m = _PMR_RE.match(tok)
    if not m:
        return None
    full, prefix, local = m.group(1), m.group(2), m.group(3)
    return full, prefix, local


@router.post("/import/rdf")
async def import_rdf(file: UploadFile = File(...)):
    """
    Import a Turtle (.ttl) file previously exported by this app.
    Uses MERGE everywhere — safe to run on a populated database (no duplicates).
    """
    if not file.filename or not file.filename.endswith(".ttl"):
        raise HTTPException(status_code=400, detail="Only .ttl (Turtle RDF) files are accepted")

    raw = (await file.read()).decode("utf-8")
    driver = get_driver()

    # State collectors
    nodes: dict[str, dict] = {}       # uri → {_type, _prefix, _lid, **props}
    involves: list[dict] = []          # InvolvesRel reified nodes
    edges: list[tuple[str, str, str, dict]] = []  # (src_uri, pred, tgt_uri, extra)

    # ── Pass 1: parse all triples ─────────────────────────────────────────────
    for m in _TRIPLE_RE.finditer(raw):
        subj, pred, obj = m.group(1), m.group(2), m.group(3)

        if pred == "a":
            # Node type declaration
            type_name = obj.replace("pm:", "")
            if subj not in nodes:
                nodes[subj] = {"_type": type_name}
            else:
                nodes[subj]["_type"] = type_name
            continue

        local_pred = pred.replace("pm:", "")

        if subj.startswith("pmr:") and obj.startswith('"'):
            # Property literal
            if subj not in nodes:
                nodes[subj] = {}
            nodes[subj][local_pred] = _parse_literal(obj)
            continue

        if subj.startswith("pmr:") and obj.startswith("pmr:"):
            edges.append((subj, local_pred, obj, {}))

    # ── Pass 2: collect InvolvesRel edges ─────────────────────────────────────
    for uri, props in nodes.items():
        if props.get("_type") == "InvolvesRel":
            involves.append(props)

    # ── Pass 3: write to Neo4j ─────────────────────────────────────────────────
    counts: dict[str, int] = {k: 0 for k in ("papers", "people", "tags", "topics", "projects", "notes", "edges", "involves")}

    with driver.session() as session:

        for uri, props in nodes.items():
            t = props.get("_type")
            p = {k: v for k, v in props.items() if not k.startswith("_")}

            if t == "Paper" and p.get("id"):
                session.run(
                    "MERGE (n:Paper {id: $id}) SET n += $props",
                    id=p["id"], props=p,
                )
                counts["papers"] += 1

            elif t == "Person" and p.get("id"):
                session.run(
                    "MERGE (n:Person {id: $id}) SET n += $props",
                    id=p["id"], props=p,
                )
                counts["people"] += 1

            elif t == "Tag" and p.get("name"):
                session.run(
                    "MERGE (n:Tag {name: $name})",
                    name=p["name"],
                )
                counts["tags"] += 1

            elif t == "Topic" and p.get("name"):
                session.run(
                    "MERGE (n:Topic {name: $name}) SET n += $props",
                    name=p["name"], props=p,
                )
                counts["topics"] += 1

            elif t == "Project" and p.get("id"):
                session.run(
                    "MERGE (n:Project {id: $id}) SET n += $props",
                    id=p["id"], props=p,
                )
                counts["projects"] += 1

            elif t == "Note" and p.get("id"):
                session.run(
                    "MERGE (n:Note {id: $id}) SET n += $props",
                    id=p["id"], props=p,
                )
                counts["notes"] += 1

        # Involves (reified)
        for inv in involves:
            paper_uri = inv.get("paper", "")
            person_uri = inv.get("person", "")
            role = inv.get("role", "")
            pu = _parse_uri(paper_uri)
            pe = _parse_uri(person_uri)
            if pu and pe:
                session.run(
                    """
                    MATCH (paper:Paper {id: $pid}), (person:Person {id: $peid})
                    MERGE (paper)-[r:INVOLVES {role: $role}]->(person)
                    """,
                    pid=pu[2], peid=pe[2], role=role,
                )
                counts["involves"] += 1

        # Edges
        REL_MAP = {
            "authoredBy":   ("Paper", "AUTHORED_BY", "Person"),
            "taggedWith":   ("Paper", "TAGGED",       "Tag"),
            "about":        ("Paper", "ABOUT",        "Topic"),
            "cites":        ("Paper", "CITES",        "Paper"),
            "inProject":    ("Paper", "IN_PROJECT",   "Project"),
            "hasNote":      ("Paper", "HAS_NOTE",     "Note"),
            "mentions":     ("Note",  "MENTIONS",     None),
            "specializesIn":("Person","SPECIALIZES_IN","Topic"),
        }

        for src_uri, pred, tgt_uri, _ in edges:
            if pred not in REL_MAP:
                continue
            src_p = _parse_uri(src_uri)
            tgt_p = _parse_uri(tgt_uri)
            if not src_p or not tgt_p:
                continue

            rel_type = REL_MAP[pred][1]
            src_prefix, tgt_prefix = src_p[1], tgt_p[1]

            # Resolve lookup key (id vs name)
            src_id_field = "name" if src_prefix in ("tag", "topic") else "id"
            tgt_id_field = "name" if tgt_prefix in ("tag", "topic") else "id"

            # URL-decode the local id (we encoded spaces/special chars)
            import urllib.parse
            src_lid = urllib.parse.unquote(src_p[2])
            tgt_lid = urllib.parse.unquote(tgt_p[2])

            # Strip trailing punctuation artefacts
            src_lid = src_lid.rstrip(" .")
            tgt_lid = tgt_lid.rstrip(" .")

            src_label = src_prefix.capitalize()
            tgt_label = tgt_prefix.capitalize()
            if src_label == "Note":
                src_label = "Note"
            if tgt_label == "Note":
                tgt_label = "Note"

            try:
                session.run(
                    f"""
                    MATCH (a:{src_label} {{{src_id_field}: $sid}})
                    MATCH (b:{tgt_label} {{{tgt_id_field}: $tid}})
                    MERGE (a)-[:{rel_type}]->(b)
                    """,
                    sid=src_lid, tid=tgt_lid,
                )
                counts["edges"] += 1
            except Exception as exc:
                log.debug("Edge import skip | %s→%s | %s", src_uri, tgt_uri, exc)

    log.info("RDF import complete | %s", counts)
    return {"imported": counts}


# ── helpers ───────────────────────────────────────────────────────────────────

def _bib_escape(s: str) -> str:
    return s.replace("{", "\\{").replace("}", "\\}")
