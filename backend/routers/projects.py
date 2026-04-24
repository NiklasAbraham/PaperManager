from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel
from db.connection import get_driver
from db.queries.projects import (
    create_project, get_project, list_projects, update_project,
    delete_project, add_paper_to_project, remove_paper_from_project,
    get_project_papers, link_projects,
)
from db.queries.conversations import list_paper_conversations, get_messages
from models.schemas import ProjectCreate, ProjectUpdate, ProjectOut, ProjectPaperLink

router = APIRouter(prefix="/projects", tags=["projects"])


def _bib_escape(s: str) -> str:
    return s.replace("{", "\\{").replace("}", "\\}").replace("&", "\\&")


class ProjectNoteBody(BaseModel):
    content: str


class ProjectKeywordsBody(BaseModel):
    content: str


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def create(body: ProjectCreate):
    return create_project(get_driver(), body.model_dump())


@router.get("")
def list_all():
    return list_projects(get_driver())


@router.get("/{project_id}")
def get_one(project_id: str):
    project = get_project(get_driver(), project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    papers = get_project_papers(get_driver(), project_id)
    return {**project, "papers": papers}


@router.patch("/{project_id}", response_model=ProjectOut)
def update(project_id: str, body: ProjectUpdate):
    data = {k: v for k, v in body.model_dump().items() if v is not None}
    project = update_project(get_driver(), project_id, data)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(project_id: str):
    if not delete_project(get_driver(), project_id):
        raise HTTPException(status_code=404, detail="Project not found")


@router.post("/{project_id}/papers", status_code=status.HTTP_201_CREATED)
def add_paper(project_id: str, body: ProjectPaperLink):
    if not get_project(get_driver(), project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    add_paper_to_project(get_driver(), body.paper_id, project_id)
    return {"project_id": project_id, "paper_id": body.paper_id}


@router.delete("/{project_id}/papers/{paper_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_paper(project_id: str, paper_id: str):
    remove_paper_from_project(get_driver(), paper_id, project_id)


@router.post("/{project_a_id}/related/{project_b_id}", status_code=status.HTTP_201_CREATED)
def relate(project_a_id: str, project_b_id: str):
    link_projects(get_driver(), project_a_id, project_b_id)
    return {"related": [project_a_id, project_b_id]}


# ── Project note ──────────────────────────────────────────────────────────────

@router.get("/{project_id}/note")
def get_note(project_id: str):
    driver = get_driver()
    with driver.session() as session:
        r = session.run(
            "MATCH (p:Project {id: $id}) RETURN p.note AS note", id=project_id
        ).single()
    if r is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"content": r["note"] or ""}


@router.put("/{project_id}/note")
def upsert_note(project_id: str, body: ProjectNoteBody):
    driver = get_driver()
    with driver.session() as session:
        r = session.run(
            "MATCH (p:Project {id: $id}) SET p.note = $note RETURN p.note AS note",
            id=project_id, note=body.content,
        ).single()
    if r is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"content": r["note"] or ""}


# ── Project keywords (for literature search) ──────────────────────────────────

@router.get("/{project_id}/keywords")
def get_keywords(project_id: str):
    driver = get_driver()
    with driver.session() as session:
        r = session.run(
            "MATCH (p:Project {id: $id}) RETURN p.keywords AS keywords", id=project_id
        ).single()
    if r is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"content": r["keywords"] or ""}


@router.put("/{project_id}/keywords")
def upsert_keywords(project_id: str, body: ProjectKeywordsBody):
    driver = get_driver()
    with driver.session() as session:
        r = session.run(
            "MATCH (p:Project {id: $id}) SET p.keywords = $kw RETURN p.keywords AS keywords",
            id=project_id, kw=body.content,
        ).single()
    if r is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"content": r["keywords"] or ""}


# ── Project exports ───────────────────────────────────────────────────────────

@router.get("/{project_id}/export/conversations")
def export_conversations(project_id: str):
    """Export all paper conversations in this project as a markdown file."""
    driver = get_driver()
    project = get_project(driver, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    papers = get_project_papers(driver, project_id)

    lines: list[str] = [f"# Conversations — {project['name']}\n"]

    for paper in papers:
        convs = list_paper_conversations(driver, paper["id"])
        if not convs:
            continue
        lines.append(f"\n## {paper.get('title', 'Untitled')}\n")
        for conv in convs:
            lines.append(f"\n### {conv.get('title', 'Conversation')}")
            if conv.get("compacted"):
                lines.append("*(compacted)*\n")
            msgs = get_messages(driver, conv["id"])
            for msg in msgs:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role == "system":
                    lines.append(f"\n> **Summary**\n>\n> {content.replace(chr(10), chr(10) + '> ')}\n")
                elif role == "user":
                    lines.append(f"\n**You:** {content}\n")
                else:
                    lines.append(f"\n**Assistant:** {content}\n")

    slug = project["name"].replace(" ", "_")[:40]
    return Response(
        "\n".join(lines),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={slug}_conversations.md"},
    )


@router.get("/{project_id}/export/bibtex")
def export_bibtex(project_id: str):
    driver = get_driver()
    project = get_project(driver, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    papers = get_project_papers(driver, project_id)

    # Fetch authors for each paper
    with driver.session() as session:
        result = session.run(
            """
            MATCH (proj:Project {id: $pid})-[:CONTAINS]->(p:Paper)
            OPTIONAL MATCH (p)-[:AUTHORED_BY]->(a:Person)
            WITH p, collect(a.name) AS authors
            RETURN p, authors ORDER BY p.title
            """,
            pid=project_id,
        )
        rows = [(dict(r["p"]), r["authors"]) for r in result]

    lines: list[str] = []
    for props, authors in rows:
        key = (props.get("id") or "unknown")[:8]
        lines.append(f"@article{{{key},")
        lines.append(f"  title  = {{{_bib_escape(props.get('title') or '')}}},")
        if authors:
            lines.append(f"  author = {{{' and '.join(authors)}}},")
        if props.get("year"):
            lines.append(f"  year   = {{{props['year']}}},")
        if props.get("doi"):
            lines.append(f"  doi    = {{{props['doi']}}},")
        if props.get("venue"):
            lines.append(f"  journal = {{{_bib_escape(props['venue'])}}},")
        lines.append("}")
        lines.append("")

    slug = project["name"].replace(" ", "_")[:40]
    return Response(
        "\n".join(lines),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={slug}.bib"},
    )


@router.get("/{project_id}/export/csv")
def export_csv(project_id: str):
    import csv, io
    driver = get_driver()
    project = get_project(driver, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    with driver.session() as session:
        result = session.run(
            """
            MATCH (proj:Project {id: $pid})-[:CONTAINS]->(p:Paper)
            OPTIONAL MATCH (p)-[:AUTHORED_BY]->(a:Person)
            OPTIONAL MATCH (p)-[:ABOUT]->(t:Topic)
            OPTIONAL MATCH (p)-[:TAGGED]->(tag:Tag)
            WITH p, collect(DISTINCT a.name) AS authors,
                 collect(DISTINCT t.name) AS topics,
                 collect(DISTINCT tag.name) AS tags
            RETURN p, authors, topics, tags ORDER BY p.title
            """,
            pid=project_id,
        )
        rows = [(dict(r["p"]), r["authors"], r["topics"], r["tags"]) for r in result]

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["title", "authors", "year", "doi", "venue", "abstract", "topics", "tags", "citation_count", "metadata_source"])
    for props, authors, topics, tags in rows:
        writer.writerow([
            props.get("title", ""),
            "; ".join(authors),
            props.get("year", ""),
            props.get("doi", ""),
            props.get("venue", ""),
            (props.get("abstract") or "").replace("\n", " "),
            "; ".join(topics),
            "; ".join(tags),
            props.get("citation_count", ""),
            props.get("metadata_source", ""),
        ])

    slug = project["name"].replace(" ", "_")[:40]
    return Response(
        buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={slug}.csv"},
    )
