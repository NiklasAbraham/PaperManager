import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from neo4j.graph import Node, Relationship

from db.connection import get_driver

log = logging.getLogger(__name__)
router = APIRouter(prefix="/cypher", tags=["cypher"])

# ── Schema description (static + enriched at runtime) ────────────────────────

SCHEMA_PROMPT = """\
You are a Neo4j Cypher query expert for a paper management system called PaperManager.

== Graph Schema ==

Node labels and their properties:
  Paper    : id (uuid), title, year (int), doi, abstract, summary, drive_file_id,
             citation_count (int), metadata_source, raw_text, created_at, updated_at
  Person   : id (uuid), name, affiliation, email
  Topic    : id (uuid), name
  Tag      : id (uuid), name
  Project  : id (uuid), name, description, status, created_at
  Note     : id (uuid), content, created_at, updated_at

Relationship types:
  (Paper)   -[:CITES]->       (Paper)    paper cites another paper (may be a stub)
  (Paper)   -[:TAGGED]->      (Tag)      paper has a tag
  (Paper)   -[:ABOUT]->       (Topic)    paper is about a topic
  (Paper)   -[:AUTHORED_BY]-> (Person)   paper has an author
  (Project) -[:CONTAINS]->    (Paper)    project contains a paper
  (Note)    -[:ABOUT]->       (Paper)    note belongs to a paper
  (Note)    -[:MENTIONS]->    (Person)   note mentions a person
  (Note)    -[:MENTIONS]->    (Topic)    note mentions a topic
  (Topic)   -[:RELATED_TO]-   (Topic)    topics are related (undirected)
  (Person)  -[:INVOLVES]->    (Paper)    non-author involvement (role stored on rel)

== Important notes ==
- Use `id` (uuid string) as the primary identifier for all nodes
- A "reference stub" is a Paper with no abstract, no drive_file_id, and no metadata_source
- Use DETACH DELETE to remove a node and all its relationships
- Use MERGE to avoid creating duplicates
- Dates are ISO 8601 strings stored as plain strings
- When referencing a specific paper by title, use toLower(p.title) CONTAINS toLower("...")
- Do not wrap results in extra objects; return fields directly

== Task ==
Generate a valid Cypher query for the following natural language request.
Return ONLY the raw Cypher — no markdown fences, no explanation, no comments.
"""


# ── Serialisation ─────────────────────────────────────────────────────────────

def _serialize(v):
    if isinstance(v, Node):
        return {"_labels": list(v.labels), **dict(v.items())}
    if isinstance(v, Relationship):
        return {"_type": v.type, **dict(v.items())}
    if isinstance(v, (list, tuple)):
        return [_serialize(i) for i in v]
    if isinstance(v, dict):
        return {k: _serialize(val) for k, val in v.items()}
    # neo4j Integer → plain int
    if hasattr(v, "__int__") and type(v).__name__ == "Integer":
        return int(v)
    return v


# ── Request models ─────────────────────────────────────────────────────────────

class QueryBody(BaseModel):
    query: str

class AssistBody(BaseModel):
    request: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/schema")
def get_schema():
    """Return live schema info (labels, relationship types, property keys per label)."""
    driver = get_driver()
    try:
        with driver.session() as session:
            labels = [r["label"] for r in session.run("CALL db.labels() YIELD label")]
            rel_types = [r["relationshipType"] for r in
                         session.run("CALL db.relationshipTypes() YIELD relationshipType")]
            properties: dict[str, list[str]] = {}
            for label in labels:
                rec = session.run(
                    f"MATCH (n:`{label}`) RETURN keys(n) AS k LIMIT 1"
                ).single()
                properties[label] = list(rec["k"]) if rec else []
        return {
            "labels": labels,
            "relationship_types": rel_types,
            "properties": properties,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/run")
def run_query(body: QueryBody):
    """Execute an arbitrary Cypher query and return rows + mutation counters."""
    query = body.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Empty query")

    driver = get_driver()
    try:
        with driver.session() as session:
            result = session.run(query)
            keys = list(result.keys())
            rows = []
            for record in result:
                row = {k: _serialize(record[k]) for k in keys}
                rows.append(row)
                if len(rows) >= 500:
                    break
            summary = result.consume()
            c = summary.counters
            counters = {
                "nodes_created":        c.nodes_created,
                "nodes_deleted":        c.nodes_deleted,
                "relationships_created": c.relationships_created,
                "relationships_deleted": c.relationships_deleted,
                "properties_set":       c.properties_set,
            }
        log.info("Cypher executed | rows=%d | query=%.80s", len(rows), query)
        return {"columns": keys, "rows": rows, "row_count": len(rows), "counters": counters}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/nodes/{node_id}", status_code=204)
def delete_node(node_id: str):
    """Delete any node by its id property (DETACH DELETE — removes all relationships too)."""
    driver = get_driver()
    with driver.session() as session:
        result = session.run(
            "MATCH (n {id: $id}) DETACH DELETE n RETURN count(n) AS deleted",
            id=node_id,
        )
        deleted = result.single()["deleted"]
    if deleted == 0:
        raise HTTPException(status_code=404, detail="Node not found")
    log.info("Node deleted | id=%s", node_id)


@router.post("/assist")
def assist_query(body: AssistBody):
    """Use Ollama to generate a Cypher query from a natural language description."""
    if not body.request.strip():
        raise HTTPException(status_code=400, detail="Empty request")
    try:
        import ollama
        from config import settings

        prompt = SCHEMA_PROMPT + f'\n"{body.request.strip()}"'
        response = ollama.chat(
            model=settings.ollama_model,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response["message"]["content"].strip()
        # Strip any markdown fences the model adds despite instructions
        for fence in ("```cypher", "```"):
            raw = raw.removeprefix(fence)
        raw = raw.removesuffix("```").strip()
        return {"query": raw}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Ollama unavailable: {e}")
