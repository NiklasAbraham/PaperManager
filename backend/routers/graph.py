import logging
import time

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from neo4j import Driver
from pydantic import BaseModel

from db.connection import get_driver
from db.queries.users import is_user_admin
from services.auth import get_current_user
from services.cypher_result import (
    GraphCollector,
    counters_dict,
    link_dict as _link_dict,  # noqa: F401 — kept for callers of the old name
    node_dict as _node_dict,
    node_id as _node_id,
    node_type as _node_type,  # noqa: F401 — kept for callers of the old name
    serialize_value,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/graph", tags=["graph"])

MAX_ROWS = 500
# Upper bound on records read to build the graph view, so a runaway MATCH cannot stall a request.
MAX_SCAN_RECORDS = 20_000


def _require_admin(driver: Driver, current_user: str) -> None:
    if not is_user_admin(driver, current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")


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
                links.append({
                    "source": _node_id(r.start_node),
                    "target": _node_id(r.end_node),
                    "type":   r.type,
                })

    return {"nodes": list(nodes.values()), "links": links}


@router.post("/cypher")
def run_cypher(
    body: dict = Body(...),
    driver: Driver = Depends(get_driver),
    current_user: str = Depends(get_current_user),
):
    """Legacy graph-only query endpoint (admin only; the Graph page uses POST /graph/query)."""
    _require_admin(driver, current_user)
    query = (body.get("query") or "").strip()
    if not query:
        return {"nodes": [], "links": [], "error": "Empty query"}

    collector = GraphCollector()
    try:
        with driver.session() as session:
            result = session.run(query)
            for record in result:
                collector.add(list(record.values()))
        nodes, links = collector.result()
        return {"nodes": nodes, "links": links}
    except Exception as exc:
        return {"nodes": [], "links": [], "error": str(exc)}


class GraphQueryBody(BaseModel):
    query: str
    read_only: bool = True


def _collect(result) -> dict:
    """Read a Cypher result once into table rows plus the graph view."""
    keys = list(result.keys())
    rows: list[dict] = []
    collector = GraphCollector()
    rows_truncated = False
    scan_cut = False
    scanned = 0
    for record in result:
        scanned += 1
        values = list(record.values())
        if len(rows) < MAX_ROWS:
            rows.append({k: serialize_value(v) for k, v in zip(keys, values)})
        else:
            rows_truncated = True
        if not collector.full:
            collector.add(values)
        # Past the row cap only the graph view still needs records.
        if rows_truncated and collector.full:
            break
        if scanned >= MAX_SCAN_RECORDS:
            scan_cut = True
            break
    summary = result.consume()
    nodes, links = collector.result()
    return {
        "columns": keys,
        "rows": rows,
        "row_count": len(rows),
        "truncated": rows_truncated,
        "counters": counters_dict(summary),
        "nodes": nodes,
        "links": links,
        "graph_truncated": collector.truncated or scan_cut,
    }


@router.post("/query")
def graph_query(
    body: GraphQueryBody,
    driver: Driver = Depends(get_driver),
    current_user: str = Depends(get_current_user),
):
    """Run one Cypher query and return the table view and the graph view together.

    Admin only. With read_only (the default) the query runs in a managed read transaction, so
    Neo4j itself rejects CREATE/MERGE/SET/DELETE; read_only=false runs it as an auto-commit
    query that may write.
    """
    _require_admin(driver, current_user)
    query = body.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Empty query")

    started = time.perf_counter()
    try:
        with driver.session() as session:
            if body.read_only:
                out = session.execute_read(lambda tx: _collect(tx.run(query)))
            else:
                out = _collect(session.run(query))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=getattr(exc, "message", None) or str(exc))
    out["took_ms"] = int((time.perf_counter() - started) * 1000)
    log.info(
        "Graph query | user=%s read_only=%s rows=%d nodes=%d | %.80s",
        current_user, body.read_only, out["row_count"], len(out["nodes"]), query,
    )
    return out
