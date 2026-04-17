from fastapi import APIRouter, Body, Depends, Query
from neo4j import Driver
from neo4j.graph import Node, Relationship

from db.connection import get_driver

router = APIRouter(prefix="/graph", tags=["graph"])

_NODE_TYPES = {
    "Paper":   "paper",
    "Person":  "person",
    "Topic":   "topic",
    "Tag":     "tag",
    "Project": "project",
    "Note":    "note",
}


def _node_type(labels: list[str]) -> str:
    for lbl in labels:
        if lbl in _NODE_TYPES:
            return _NODE_TYPES[lbl]
    return "unknown"


def _node_dict(node) -> dict:
    props = dict(node)
    return {
        "id":    props.get("id") or str(node.element_id),
        "label": props.get("title") or props.get("name") or props.get("id", "?"),
        "type":  _node_type(list(node.labels)),
        **{k: v for k, v in props.items() if k not in ("raw_text",)},
    }


def _link_dict(rel) -> dict:
    return {
        "source": str(rel.start_node.element_id),
        "target": str(rel.end_node.element_id),
        "type":   rel.type,
    }


@router.get("")
def get_graph(
    mode: str = Query("full", pattern="^(full|papers|paper)$"),
    id: str | None = Query(None),
    driver: Driver = Depends(get_driver),
):
    """
    Returns {nodes, links} for the graph.

    mode=full   → all nodes + relationships (limit 500)
    mode=papers → Paper, Person, Topic nodes only
    mode=paper  → single paper and its direct neighbours (requires ?id=)
    """
    nodes: dict[str, dict] = {}
    links: list[dict] = []

    with driver.session() as session:
        if mode == "paper" and id:
            cypher = """
                MATCH (center:Paper {id: $id})
                OPTIONAL MATCH (center)-[r]-(neighbor)
                RETURN center, r, neighbor
            """
            result = session.run(cypher, id=id)

        elif mode == "papers":
            cypher = """
                MATCH (n)
                WHERE n:Paper OR n:Person OR n:Topic
                OPTIONAL MATCH (n)-[r]-(m)
                WHERE m:Paper OR m:Person OR m:Topic
                RETURN n, r, m
                LIMIT 500
            """
            result = session.run(cypher)

        else:  # full
            cypher = """
                MATCH (n)
                OPTIONAL MATCH (n)-[r]->(m)
                RETURN n, r, m
                LIMIT 150
            """
            result = session.run(cypher)

        for record in result:
            n = record.get("n") or record.get("center")
            if n is not None:
                nd = _node_dict(n)
                nodes[nd["id"]] = nd

            m = record.get("m") or record.get("neighbor")
            if m is not None:
                md = _node_dict(m)
                nodes[md["id"]] = md

            r = record.get("r")
            if r is not None:
                # Re-map source/target to our stable id field
                src_node = r.start_node
                tgt_node = r.end_node
                src_id = dict(src_node).get("id") or str(src_node.element_id)
                tgt_id = dict(tgt_node).get("id") or str(tgt_node.element_id)
                links.append({
                    "source": src_id,
                    "target": tgt_id,
                    "type":   r.type,
                })

    return {"nodes": list(nodes.values()), "links": links}


@router.post("/cypher")
def run_cypher(
    body: dict = Body(...),
    driver: Driver = Depends(get_driver),
):
    query = (body.get("query") or "").strip()
    if not query:
        return {"nodes": [], "links": [], "error": "Empty query"}

    nodes: dict[str, dict] = {}
    links: list[dict] = []

    try:
        with driver.session() as session:
            result = session.run(query)
            for record in result:
                for value in record.values():
                    if isinstance(value, Node):
                        nd = _node_dict(value)
                        nodes[nd["id"]] = nd
                    elif isinstance(value, Relationship):
                        src_id = dict(value.start_node).get("id") or str(value.start_node.element_id)
                        tgt_id = dict(value.end_node).get("id") or str(value.end_node.element_id)
                        links.append({"source": src_id, "target": tgt_id, "type": value.type})
        return {"nodes": list(nodes.values()), "links": links}
    except Exception as exc:
        return {"nodes": [], "links": [], "error": str(exc)}
