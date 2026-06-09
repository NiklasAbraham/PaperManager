from fastapi import APIRouter, Body, Depends, Query
from neo4j import Driver
from neo4j.graph import Node, Relationship

from db.connection import get_driver

router = APIRouter(prefix="/graph", tags=["graph"])

_NODE_TYPES = {
    "Paper":    "paper",
    "Person":   "person",
    "Topic":    "topic",
    "Tag":      "tag",
    "Project":  "project",
    "Note":     "note",
    "BlogPost": "blogpost",
    "Blog":     "blog",
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
        **{k: v for k, v in props.items() if k not in ("raw_text", "content", "content_md")},
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
    max_nodes: int = Query(2000, ge=1, le=10000),
    driver: Driver = Depends(get_driver),
):
    """
    Returns {nodes, links} for the graph.

    mode=full   → all nodes + relationships (up to max_nodes nodes)
    mode=papers → Paper, Person, Topic, Project nodes only
    mode=paper  → single paper and its direct neighbours (requires ?id=)

    The LIMIT is applied to the number of matched nodes (via WITH … LIMIT),
    not to the number of result rows, so all papers are included up to max_nodes.
    """
    nodes: dict[str, dict] = {}
    links: list[dict] = []

    from db.queries.visibility import node_visibility_clause

    vis_n, vis_params = node_visibility_clause("n")
    vis_m, _ = node_visibility_clause("m")
    vis_center, _ = node_visibility_clause("center")
    vis_neighbor, _ = node_visibility_clause("neighbor")

    with driver.session() as session:
        if mode == "paper" and id:
            cypher = f"""
                MATCH (center:Paper {{id: $id}})
                WHERE {vis_center}
                OPTIONAL MATCH (center)-[r]-(neighbor)
                WHERE neighbor IS NULL OR ({vis_neighbor})
                RETURN center, r, neighbor
            """
            result = session.run(cypher, id=id, **vis_params)

        elif mode == "papers":
            cypher = f"""
                MATCH (n)
                WHERE (n:Paper OR n:Person OR n:Topic OR n:Project)
                  AND {vis_n}
                WITH n LIMIT $max_nodes
                OPTIONAL MATCH (n)-[r]-(m)
                WHERE (m:Paper OR m:Person OR m:Topic OR m:Project)
                  AND ({vis_m})
                RETURN n, r, m
            """
            result = session.run(cypher, max_nodes=max_nodes, **vis_params)

        else:  # full
            cypher = f"""
                MATCH (n)
                WHERE {vis_n}
                WITH n LIMIT $max_nodes
                OPTIONAL MATCH (n)-[r]->(m)
                WHERE m IS NULL OR ({vis_m})
                RETURN n, r, m
            """
            result = session.run(cypher, max_nodes=max_nodes, **vis_params)

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
