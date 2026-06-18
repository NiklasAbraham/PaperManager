"""
In-memory fake Neo4j driver for CI-friendly end-to-end tests.

Implements a minimal graph store that supports the Cypher patterns used by
PaperManager's query layer. This allows realistic integration testing of the
full HTTP → router → query → response pipeline without a real Neo4j instance.
"""
from __future__ import annotations

import re
import uuid
from typing import Any
from dataclasses import dataclass, field


# ── Graph model ───────────────────────────────────────────────────────────────

@dataclass
class FakeNode:
    labels: set[str]
    props: dict[str, Any]
    element_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def __getitem__(self, key):
        return self.props[key]

    def __contains__(self, key):
        return key in self.props

    def get(self, key, default=None):
        return self.props.get(key, default)

    def items(self):
        return self.props.items()

    def keys(self):
        return self.props.keys()

    def values(self):
        return self.props.values()

    def __iter__(self):
        return iter(self.props)


@dataclass
class FakeRelationship:
    start_node: FakeNode
    end_node: FakeNode
    rel_type: str

    @property
    def type(self):
        return self.rel_type


# ── In-memory store ───────────────────────────────────────────────────────────

class FakeGraphStore:
    """Thread-safe in-memory graph store."""

    def __init__(self):
        self.nodes: list[FakeNode] = []
        self.relationships: list[FakeRelationship] = []

    def add_node(self, labels: set[str], props: dict) -> FakeNode:
        node = FakeNode(labels=labels, props=dict(props))
        self.nodes.append(node)
        return node

    def find_node(self, label: str, **match_props) -> FakeNode | None:
        for node in self.nodes:
            if label in node.labels:
                if all(node.props.get(k) == v for k, v in match_props.items()):
                    return node
        return None

    def find_nodes(self, label: str, **match_props) -> list[FakeNode]:
        results = []
        for node in self.nodes:
            if label in node.labels:
                if all(node.props.get(k) == v for k, v in match_props.items()):
                    results.append(node)
        return results

    def delete_node(self, node: FakeNode):
        self.relationships = [
            r for r in self.relationships
            if r.start_node is not node and r.end_node is not node
        ]
        self.nodes = [n for n in self.nodes if n is not node]

    def add_relationship(self, start: FakeNode, end: FakeNode, rel_type: str) -> FakeRelationship:
        # Don't duplicate
        for r in self.relationships:
            if r.start_node is start and r.end_node is end and r.rel_type == rel_type:
                return r
        rel = FakeRelationship(start_node=start, end_node=end, rel_type=rel_type)
        self.relationships.append(rel)
        return rel

    def delete_relationship(self, start: FakeNode, end: FakeNode, rel_type: str):
        self.relationships = [
            r for r in self.relationships
            if not (r.start_node is start and r.end_node is end and r.rel_type == rel_type)
        ]

    def get_neighbors(self, node: FakeNode) -> list[tuple[FakeRelationship, FakeNode]]:
        results = []
        for r in self.relationships:
            if r.start_node is node:
                results.append((r, r.end_node))
            elif r.end_node is node:
                results.append((r, r.start_node))
        return results

    def clear(self):
        self.nodes.clear()
        self.relationships.clear()


# ── Fake Result / Record ──────────────────────────────────────────────────────

class FakeRecord:
    def __init__(self, data: dict):
        self._data = data

    def __getitem__(self, key):
        return self._data[key]

    def get(self, key, default=None):
        return self._data.get(key, default)

    def values(self):
        return self._data.values()

    def data(self):
        return self._data


class FakeResult:
    def __init__(self, records: list[FakeRecord] | None = None):
        self._records = records or []
        self._index = 0

    def single(self):
        if self._records:
            return self._records[0]
        return None

    def data(self):
        return [r.data() for r in self._records]

    def consume(self):
        """No-op for compatibility with neo4j Result.consume()."""
        return None

    def __iter__(self):
        return iter(self._records)

    def __next__(self):
        if self._index < len(self._records):
            r = self._records[self._index]
            self._index += 1
            return r
        raise StopIteration


# ── Cypher interpreter (minimal) ──────────────────────────────────────────────

class FakeCypherSession:
    """Interprets a minimal subset of Cypher for the patterns used by PaperManager."""

    def __init__(self, store: FakeGraphStore):
        self.store = store

    def run(self, query: str, **params) -> FakeResult:
        q = query.strip()

        # CREATE (p:Label $props) RETURN p
        m = re.search(r"CREATE\s+\((\w+):(\w+)\s+\$(\w+)\)\s+RETURN\s+\w+", q)
        if m:
            var, label, param_name = m.groups()
            props = params.get(param_name, {})
            node = self.store.add_node({label}, props)
            return FakeResult([FakeRecord({var: node})])

        # MATCH (p:Label {id: $id}) DETACH DELETE p RETURN count(p) AS deleted
        m = re.search(r"MATCH\s+\((\w+):(\w+)\s+\{id:\s*\$(\w+)\}\)\s+DETACH DELETE", q)
        if m:
            var, label, param_name = m.groups()
            node_id = params.get(param_name, params.get("id"))
            node = self.store.find_node(label, id=node_id)
            if node:
                self.store.delete_node(node)
                return FakeResult([FakeRecord({"deleted": 1})])
            return FakeResult([FakeRecord({"deleted": 0})])

        # MATCH (p:Label {id: $id}) SET p += $props RETURN p (+ optional user join)
        if re.search(r"MATCH\s+\(\w+:\w+\s+\{id:\s*\$id\}\)\s*\n?\s*SET\s+\w+\s*\+=\s*\$props", q):
            label_m = re.search(r"\((\w+):(\w+)\s+\{id:", q)
            if label_m:
                var, label = label_m.groups()
                node = self.store.find_node(label, id=params.get("id"))
                if node:
                    node.props.update(params.get("props", {}))
                    # Check for user attribution
                    if "added_user" in q or "added_by" in q:
                        return FakeResult([FakeRecord({var: node, "added_by": None, "added_by_color": None})])
                    return FakeResult([FakeRecord({var: node})])
            return FakeResult([])

        # MATCH (p:Label {id: $id}) RETURN p (simple get)
        m = re.search(r"MATCH\s+\((\w+):(\w+)\s+\{id:\s*\$(\w+)\}\)\s*\n?\s*(?:OPTIONAL MATCH.*\n?)*\s*(?:WITH.*\n?)?\s*RETURN", q)
        if m and "SET" not in q and "DELETE" not in q and "MERGE" not in q:
            var, label, param_name = m.groups()
            node_id = params.get(param_name, params.get("id"))
            node = self.store.find_node(label, id=node_id)
            if node:
                if "added_by" in q or "added_user" in q:
                    return FakeResult([FakeRecord({var: node, "added_by": None, "added_by_color": None})])
                return FakeResult([FakeRecord({var: node})])
            return FakeResult([])

        # MERGE (t:Label {name: $name}) ON CREATE SET t.id = $id RETURN t
        m = re.search(r"MERGE\s+\((\w+):(\w+)\s+\{name:\s*\$name\}\)", q)
        if m and "RETURN" in q:
            var, label = m.groups()
            name = params.get("name")
            node = self.store.find_node(label, name=name)
            if not node:
                props = {"name": name, "id": params.get("id", str(uuid.uuid4()))}
                node = self.store.add_node({label}, props)
            return FakeResult([FakeRecord({var: node})])

        # MERGE (p:Paper {doi: $doi}) ... RETURN p
        if "MERGE" in q and "Paper" in q and "doi" in q:
            doi = params.get("doi")
            node = self.store.find_node("Paper", doi=doi)
            if not node:
                props = {
                    "id": params.get("id", str(uuid.uuid4())),
                    "title": params.get("title", ""),
                    "year": params.get("year"),
                    "doi": doi,
                    "abstract": params.get("abstract"),
                    "summary": params.get("summary"),
                    "drive_file_id": params.get("drive_file_id"),
                    "raw_text": params.get("raw_text", ""),
                    "citation_count": params.get("citation_count"),
                    "metadata_source": params.get("metadata_source"),
                    "venue": params.get("venue"),
                    "document_type": params.get("document_type"),
                    "created_at": params.get("now"),
                    "updated_at": params.get("now"),
                }
                node = self.store.add_node({"Paper"}, props)
            else:
                # ON MATCH: update
                if params.get("title"):
                    node.props["title"] = params["title"]
                for field in ("year", "abstract", "summary", "citation_count", "venue", "document_type"):
                    if params.get(field) is not None:
                        node.props[field] = params[field]
                node.props["metadata_source"] = params.get("metadata_source")
                node.props["updated_at"] = params.get("now")
            return FakeResult([FakeRecord({"p": node})])

        # MATCH ... MERGE (p)-[:REL]->(t) (link creation)
        m = re.search(r"MATCH\s+\((\w+):\w+\s+\{id:\s*\$(\w+)\}\),\s*\((\w+):\w+\s+\{id:\s*\$(\w+)\}\)\s*\n?\s*MERGE\s+\(\w+\)-\[:(\w+)\]->\(\w+\)", q)
        if m:
            _, pid_param, _, tid_param, rel_type = m.groups()
            src_id = params.get(pid_param)
            tgt_id = params.get(tid_param)
            src_node = None
            tgt_node = None
            for node in self.store.nodes:
                if node.props.get("id") == src_id:
                    src_node = node
                if node.props.get("id") == tgt_id:
                    tgt_node = node
            if src_node and tgt_node:
                self.store.add_relationship(src_node, tgt_node, rel_type)
            return FakeResult([])

        # MATCH (p:Paper {id: $pid})-[r:TAGGED]->(t:Tag {name: $name}) DELETE r
        if "DELETE r" in q and "TAGGED" in q:
            pid = params.get("pid")
            tag_name = params.get("name")
            src = self.store.find_node("Paper", id=pid)
            tgt = self.store.find_node("Tag", name=tag_name)
            if src and tgt:
                self.store.delete_relationship(src, tgt, "TAGGED")
            return FakeResult([])

        # MATCH (p:Paper {id: $id})-[:TAGGED]->(t:Tag) RETURN t
        if "TAGGED" in q and "RETURN t" in q and "id" in params:
            paper = self.store.find_node("Paper", id=params["id"])
            if paper:
                results = []
                for r in self.store.relationships:
                    if r.start_node is paper and r.rel_type == "TAGGED":
                        results.append(FakeRecord({"t": r.end_node}))
                return FakeResult(results)
            return FakeResult([])

        # MATCH (t:Tag) ... RETURN t, count ... (list tags)
        if re.search(r"MATCH\s+\(t:Tag\)", q) and "RETURN" in q:
            tags = self.store.find_nodes("Tag")
            results = []
            for tag in tags:
                paper_count = sum(
                    1 for r in self.store.relationships
                    if r.end_node is tag and r.rel_type == "TAGGED"
                    and "Paper" in r.start_node.labels
                )
                person_count = sum(
                    1 for r in self.store.relationships
                    if r.end_node is tag and r.rel_type == "TAGGED"
                    and "Person" in r.start_node.labels
                )
                results.append(FakeRecord({"t": tag, "paper_count": paper_count, "person_count": person_count}))
            return FakeResult(results)

        # MATCH (t:Topic) ... RETURN t, count (list topics)
        if re.search(r"MATCH\s+\(t:Topic\)", q) and "RETURN" in q:
            topics = self.store.find_nodes("Topic")
            results = []
            for topic in topics:
                paper_count = sum(
                    1 for r in self.store.relationships
                    if r.end_node is topic and r.rel_type == "ABOUT"
                )
                results.append(FakeRecord({"t": topic, "paper_count": paper_count}))
            return FakeResult(results)

        # MATCH (p:Person) ... list people
        if re.search(r"MATCH\s+\(p:Person\)", q) and "RETURN" in q and "DELETE" not in q:
            people = self.store.find_nodes("Person")
            results = []
            for person in people:
                paper_count = sum(
                    1 for r in self.store.relationships
                    if r.end_node is person and r.rel_type in ("AUTHORED_BY", "INVOLVES")
                )
                results.append(FakeRecord({"p": person, "paper_count": paper_count}))
            return FakeResult(results)

        # MATCH (p:Paper {id: $pid})-[:HAS_NOTE]->(n:Note) RETURN n
        if "HAS_NOTE" in q and "RETURN n" in q and "MERGE" not in q:
            pid = params.get("pid")
            paper = self.store.find_node("Paper", id=pid) or self.store.find_node("Person", id=pid)
            if paper:
                for r in self.store.relationships:
                    if r.start_node is paper and r.rel_type == "HAS_NOTE":
                        return FakeResult([FakeRecord({"n": r.end_node})])
            return FakeResult([])

        # MERGE (p)-[:HAS_NOTE]->(n:Note) (upsert note)
        if "HAS_NOTE" in q and "MERGE" in q:
            pid = params.get("pid")
            content = params.get("content")
            now = params.get("now")
            paper = self.store.find_node("Paper", id=pid) or self.store.find_node("Person", id=pid)
            if paper:
                # Check existing note
                for r in self.store.relationships:
                    if r.start_node is paper and r.rel_type == "HAS_NOTE":
                        r.end_node.props["content"] = content
                        r.end_node.props["updated_at"] = now
                        return FakeResult([FakeRecord({"n": r.end_node})])
                # Create new note
                note_id = params.get("id", str(uuid.uuid4()))
                note = self.store.add_node({"Note"}, {
                    "id": note_id, "content": content,
                    "created_at": now, "updated_at": now,
                })
                self.store.add_relationship(paper, note, "HAS_NOTE")
                return FakeResult([FakeRecord({"n": note})])
            return FakeResult([])

        # MATCH (p:Paper) list papers (with visibility / ordering)
        if re.search(r"MATCH\s+\(p:Paper\)", q) and "RETURN" in q and "DELETE" not in q and "count" not in q.lower():
            papers = self.store.find_nodes("Paper")
            # Filter out from-references papers if the query requires it
            if "from-references" in q:
                papers = [p for p in papers if not self._has_tag(p, "from-references")]
            results = []
            for paper in papers:
                rec = {"p": paper, "added_by": None, "added_by_color": None}
                if "matched_in" in q:
                    rec["score"] = 0.0
                    rec["matched_in"] = "filter"
                results.append(FakeRecord(rec))
            return FakeResult(results)

        # Stats queries: MATCH (n:Label) RETURN count(n) AS c
        m = re.search(r"MATCH\s+\(n:(\w+)\)\s+(?:WHERE.*?)?\s*RETURN\s+count\(n\)\s+AS\s+c", q, re.DOTALL)
        if m:
            label = m.group(1)
            nodes = self.store.find_nodes(label)
            if "from-references" in q:
                nodes = [n for n in nodes if not self._has_tag(n, "from-references")]
            return FakeResult([FakeRecord({"c": len(nodes)})])

        # Paper search: toLower matching
        if "toLower" in q and "Paper" in q and "title" in q:
            title = params.get("title", "")
            papers = self.store.find_nodes("Paper")
            matches = [p for p in papers if p.props.get("title", "").lower() == title.lower()]
            if matches:
                return FakeResult([FakeRecord({"p": matches[0]})])
            return FakeResult([])

        # Stats: papers_by_year
        if "p.year" in q and "count(p)" in q and "ORDER BY year" in q:
            papers = self.store.find_nodes("Paper")
            year_counts: dict[int, int] = {}
            for p in papers:
                yr = p.props.get("year")
                if yr is not None:
                    year_counts[yr] = year_counts.get(yr, 0) + 1
            results = [FakeRecord({"year": y, "count": c}) for y, c in sorted(year_counts.items())]
            return FakeResult(results)

        # Stats: top_topics
        if "t.name AS name" in q and "count(p) AS count" in q and "Topic" in q:
            topics = self.store.find_nodes("Topic")
            results = []
            for t in topics:
                cnt = sum(1 for r in self.store.relationships if r.end_node is t and r.rel_type == "ABOUT")
                if cnt > 0:
                    results.append(FakeRecord({"name": t.props.get("name"), "count": cnt}))
            results.sort(key=lambda r: r._data["count"], reverse=True)
            return FakeResult(results[:8])

        # Stats: recent papers
        if "p.id AS id" in q and "p.title AS title" in q and "ORDER BY p.created_at DESC" in q:
            papers = self.store.find_nodes("Paper")
            papers = [p for p in papers if not self._has_tag(p, "from-references")]
            papers.sort(key=lambda p: p.props.get("created_at", ""), reverse=True)
            results = []
            for p in papers[:6]:
                authors = [
                    r.end_node.props.get("name")
                    for r in self.store.relationships
                    if r.start_node is p and r.rel_type == "AUTHORED_BY"
                ]
                results.append(FakeRecord({
                    "id": p.props.get("id"),
                    "title": p.props.get("title"),
                    "year": p.props.get("year"),
                    "doi": p.props.get("doi"),
                    "metadata_source": p.props.get("metadata_source"),
                    "created_at": p.props.get("created_at"),
                    "authors": authors,
                }))
            return FakeResult(results)

        # Stats: reading_status
        if "reading_status" in q and "count(p) AS count" in q:
            papers = self.store.find_nodes("Paper")
            papers = [p for p in papers if not self._has_tag(p, "from-references")]
            status_counts: dict[str, int] = {}
            for p in papers:
                s = p.props.get("reading_status") or "unread"
                status_counts[s] = status_counts.get(s, 0) + 1
            results = [FakeRecord({"status": s, "count": c}) for s, c in sorted(status_counts.items())]
            return FakeResult(results)

        # Stats: bookmarked
        if "bookmarked = true" in q and "count(p) AS c" in q:
            papers = self.store.find_nodes("Paper")
            count = sum(1 for p in papers if p.props.get("bookmarked") is True)
            return FakeResult([FakeRecord({"c": count})])

        # MATCH (p:Paper {id: $pid}), (t:Tag {id: $tid}) MERGE (p)-[:TAGGED]->(t)
        # Already handled by generic MERGE link above

        # MATCH ... MATCH (p:Paper)-[:AUTHORED_BY]->(person) for author listing
        if "AUTHORED_BY" in q and ("paper_id" in params or "id" in params):
            pid = params.get("paper_id", params.get("id"))
            paper = self.store.find_node("Paper", id=pid)
            if paper:
                results = []
                for r in self.store.relationships:
                    if r.start_node is paper and r.rel_type == "AUTHORED_BY":
                        results.append(FakeRecord({"p": r.end_node}))
                return FakeResult(results)
            return FakeResult([])

        # Project listing with paper_count
        if re.search(r"MATCH\s+\(proj:Project\)", q) and "RETURN" in q:
            projects = self.store.find_nodes("Project")
            results = []
            for proj in projects:
                paper_count = sum(
                    1 for r in self.store.relationships
                    if r.end_node is proj and r.rel_type == "IN_PROJECT"
                )
                results.append(FakeRecord({"proj": proj, "paper_count": paper_count}))
            return FakeResult(results)

        # Get project papers
        if "IN_PROJECT" in q and "RETURN" in q and "projid" in params:
            proj = self.store.find_node("Project", id=params["projid"])
            if proj:
                results = []
                for r in self.store.relationships:
                    if r.end_node is proj and r.rel_type == "IN_PROJECT":
                        results.append(FakeRecord({"p": r.start_node, "added_by": None, "added_by_color": None}))
                return FakeResult(results)
            return FakeResult([])

        # fulltext search (return all papers as fallback)
        if "paper_search" in q or "note_search" in q:
            papers = self.store.find_nodes("Paper")
            results = []
            search_term = params.get("q", "").lower()
            matched_in = "paper" if "paper_search" in q else "note"
            for p in papers:
                title = (p.props.get("title") or "").lower()
                abstract = (p.props.get("abstract") or "").lower()
                if search_term in title or search_term in abstract:
                    results.append(FakeRecord({
                        "node": p, "score": 1.0,
                        "p": p, "matched_in": matched_in,
                        "added_by": None, "added_by_color": None,
                    }))
            return FakeResult(results)

        # Catch-all for graph queries
        if "MATCH (n)" in q or "MATCH (center:" in q:
            return FakeResult([])

        # Schema/constraint queries (no-op)
        if any(kw in q.upper() for kw in ("CREATE CONSTRAINT", "CREATE INDEX", "SHOW CONSTRAINT", "SHOW INDEX")):
            return FakeResult([])

        # Default empty result
        return FakeResult([])

    def _has_tag(self, node: FakeNode, tag_name: str) -> bool:
        for r in self.store.relationships:
            if r.start_node is node and r.rel_type == "TAGGED":
                if r.end_node.props.get("name") == tag_name:
                    return True
        return False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


# ── Fake Session / Driver ─────────────────────────────────────────────────────

class FakeSession:
    def __init__(self, store: FakeGraphStore):
        self._cypher = FakeCypherSession(store)

    def run(self, query: str, **params):
        # Handle both keyword params and params passed as positional dict
        return self._cypher.run(query, **params)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class FakeDriver:
    """Drop-in replacement for neo4j.Driver for testing."""

    def __init__(self):
        self.store = FakeGraphStore()

    def session(self) -> FakeSession:
        return FakeSession(self.store)

    def verify_connectivity(self):
        pass

    def close(self):
        pass
