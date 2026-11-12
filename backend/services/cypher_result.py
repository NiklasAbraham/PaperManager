"""Shared helpers for routers that run free-form Cypher (/cypher/run, /graph/query, /graph/cypher).

serialize_value turns driver values (nodes, relationships, paths, temporal types) into JSON for
the result table. GraphCollector walks the same values and gathers every node, relationship and
path into the {nodes, links} shape the force-graph view uses.
"""
from __future__ import annotations

from neo4j.graph import Node, Path, Relationship
from neo4j.time import Date, DateTime, Duration, Time

MAX_GRAPH_NODES = 5000

NODE_TYPES = {
    "Paper":    "paper",
    "Person":   "person",
    "Topic":    "topic",
    "Tag":      "tag",
    "Project":  "project",
    "Note":     "note",
    "BlogPost": "blogpost",
    "Blog":     "blog",
}

# Properties that are too big to ship with every node of a graph.
_HEAVY_PROPS = ("raw_text", "content", "content_md")


def node_type(labels) -> str:
    for lbl in labels:
        if lbl in NODE_TYPES:
            return NODE_TYPES[lbl]
    return "unknown"


def node_id(node) -> str:
    """Stable id of a node: its `id` property, else the database element id."""
    return str(dict(node).get("id") or node.element_id)


def serialize_value(v):
    """Make one driver value JSON-safe (nodes, relationships, paths, temporal values)."""
    if isinstance(v, Node):
        return {"_labels": list(v.labels), **{k: serialize_value(x) for k, x in v.items()}}
    if isinstance(v, Relationship):
        return {"_type": v.type, **{k: serialize_value(x) for k, x in v.items()}}
    if isinstance(v, Path):
        return {
            "_nodes": [serialize_value(n) for n in v.nodes],
            "_relationships": [serialize_value(r) for r in v.relationships],
        }
    if isinstance(v, (list, tuple, set, frozenset)):
        return [serialize_value(i) for i in v]
    if isinstance(v, dict):
        return {k: serialize_value(val) for k, val in v.items()}
    if isinstance(v, (Date, DateTime, Time, Duration)):
        return str(v)
    # neo4j Integer -> plain int
    if hasattr(v, "__int__") and type(v).__name__ == "Integer":
        return int(v)
    return v


def node_dict(node) -> dict:
    """The explorer's node format: id, display label, type and the node's properties."""
    props = dict(node)
    return {
        "id":    node_id(node),
        "label": props.get("title") or props.get("name") or props.get("id", "?"),
        "type":  node_type(list(node.labels)),
        **{k: serialize_value(v) for k, v in props.items() if k not in _HEAVY_PROPS},
    }


def link_dict(rel) -> dict:
    return {
        "source": node_id(rel.start_node),
        "target": node_id(rel.end_node),
        "type":   rel.type,
    }


def counters_dict(summary) -> dict:
    c = summary.counters
    return {
        "nodes_created":         c.nodes_created,
        "nodes_deleted":         c.nodes_deleted,
        "relationships_created": c.relationships_created,
        "relationships_deleted": c.relationships_deleted,
        "properties_set":        c.properties_set,
    }


class GraphCollector:
    """Collects the distinct nodes and links found in any number of result values."""

    def __init__(self, max_nodes: int = MAX_GRAPH_NODES) -> None:
        self.max_nodes = max_nodes
        self.truncated = False
        self._nodes: dict[str, dict] = {}
        self._links: dict[str, dict] = {}

    def _add_node(self, node) -> None:
        if node is None:
            return
        nid = node_id(node)
        if nid in self._nodes:
            return
        if len(self._nodes) >= self.max_nodes:
            self.truncated = True
            return
        self._nodes[nid] = node_dict(node)

    def _add_rel(self, rel) -> None:
        # A relationship brings its end points with it, so `RETURN r` alone still draws.
        start, end = rel.start_node, rel.end_node
        if start is None or end is None:
            return
        self._add_node(start)
        self._add_node(end)
        self._links.setdefault(str(rel.element_id), link_dict(rel))

    def add(self, value) -> None:
        if isinstance(value, Node):
            self._add_node(value)
        elif isinstance(value, Relationship):
            self._add_rel(value)
        elif isinstance(value, Path):
            for n in value.nodes:
                self._add_node(n)
            for r in value.relationships:
                self._add_rel(r)
        elif isinstance(value, (list, tuple, set, frozenset)):
            for item in value:
                self.add(item)
        elif isinstance(value, dict):
            for item in value.values():
                self.add(item)

    @property
    def full(self) -> bool:
        return len(self._nodes) >= self.max_nodes

    def result(self) -> tuple[list[dict], list[dict]]:
        """(nodes, links); links whose end point was cut by the node cap are dropped."""
        ids = self._nodes.keys()
        links = [l for l in self._links.values() if l["source"] in ids and l["target"] in ids]
        return list(self._nodes.values()), links
