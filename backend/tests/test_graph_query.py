"""POST /graph/query: admin gate, one run for table and graph views, read-only transaction.

No Neo4j needed: the driver is a fake whose results hold real neo4j Node / Relationship / Path
objects, so the serialisation and graph extraction run on the driver's own types.
"""
import pytest
from httpx import ASGITransport, AsyncClient
from neo4j.graph import Graph, Node, Path

from db.connection import get_driver
from main import app
from routers import cypher as cypher_router
from routers import graph as graph_router
from services.auth import get_current_user
from services.cypher_result import GraphCollector, serialize_value


# ── builders for driver objects ───────────────────────────────────────────────

_graph = Graph()


def make_node(eid, labels, **props):
    return Node(_graph, eid, abs(hash(eid)) % 10_000, labels, props)


def make_rel(eid, rel_type, start, end, **props):
    rel = _graph.relationship_type(rel_type)(_graph, eid, abs(hash(eid)) % 10_000, props)
    rel._start_node = start
    rel._end_node = end
    return rel


class FakeCounters:
    nodes_created = 0
    nodes_deleted = 0
    relationships_created = 0
    relationships_deleted = 0
    properties_set = 0

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


class FakeSummary:
    def __init__(self, counters):
        self.counters = counters


class FakeResult:
    def __init__(self, keys, records, counters=None):
        self._keys = keys
        self._records = records
        self._counters = counters or FakeCounters()
        self.consumed = False

    def keys(self):
        return list(self._keys)

    def __iter__(self):
        return iter(FakeRecord(r) for r in self._records)

    def consume(self):
        self.consumed = True
        return FakeSummary(self._counters)


class FakeRecord:
    def __init__(self, values):
        self._values = list(values)

    def values(self):
        return list(self._values)


class FakeTx:
    def __init__(self, result, log):
        self._result, self._log = result, log

    def run(self, query, **_):
        self._log.append(("tx.run", query))
        return self._result


class FakeSession:
    def __init__(self, result, log, error=None):
        self._result, self._log, self._error = result, log, error

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute_read(self, fn):
        self._log.append(("execute_read", None))
        if self._error:
            raise self._error
        return fn(FakeTx(self._result, self._log))

    def run(self, query, **_):
        self._log.append(("session.run", query))
        if self._error:
            raise self._error
        return self._result


class FakeDriver:
    def __init__(self, result=None, error=None):
        self.log = []
        self._result, self._error = result, error

    def session(self, **_):
        return FakeSession(self._result, self.log, self._error)


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def admin(monkeypatch):
    monkeypatch.setattr(graph_router, "is_user_admin", lambda d, u: u == "boss")
    app.dependency_overrides[get_current_user] = lambda: "boss"
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def use_driver():
    def _use(driver):
        app.dependency_overrides[get_driver] = lambda: driver
        return driver
    yield _use
    app.dependency_overrides.pop(get_driver, None)


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as c:
        yield c


def _post(client, query="MATCH (n) RETURN n", **kw):
    return client.post("/graph/query", json={"query": query, **kw})


# ── access control ────────────────────────────────────────────────────────────

async def test_unauthenticated_is_401(client, use_driver):
    use_driver(FakeDriver(FakeResult(["n"], [])))
    app.dependency_overrides.pop(get_current_user, None)
    r = await _post(client)
    assert r.status_code == 401


async def test_non_admin_is_403_and_nothing_runs(client, use_driver, monkeypatch):
    monkeypatch.setattr(graph_router, "is_user_admin", lambda d, u: False)
    app.dependency_overrides[get_current_user] = lambda: "mate"
    drv = use_driver(FakeDriver(FakeResult(["n"], [])))
    try:
        r = await _post(client)
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 403
    assert drv.log == []


async def test_empty_query_is_400(admin, client, use_driver):
    drv = use_driver(FakeDriver(FakeResult([], [])))
    for q in ("", "   \n"):
        r = await _post(client, q)
        assert r.status_code == 400
    assert drv.log == []


async def test_legacy_graph_cypher_requires_admin(client, use_driver, monkeypatch):
    monkeypatch.setattr(graph_router, "is_user_admin", lambda d, u: False)
    app.dependency_overrides[get_current_user] = lambda: "mate"
    drv = use_driver(FakeDriver(FakeResult(["n"], [])))
    try:
        r = await client.post("/graph/cypher", json={"query": "MATCH (n) DETACH DELETE n"})
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 403
    assert drv.log == []


async def test_delete_node_requires_admin(client, monkeypatch):
    monkeypatch.setattr(cypher_router, "is_user_admin", lambda d, u: False)
    monkeypatch.setattr(cypher_router, "get_driver", lambda: FakeDriver())
    app.dependency_overrides[get_current_user] = lambda: "mate"
    try:
        r = await client.delete("/cypher/nodes/abc")
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 403


# ── transaction mode ──────────────────────────────────────────────────────────

async def test_read_only_default_uses_execute_read(admin, client, use_driver):
    drv = use_driver(FakeDriver(FakeResult(["x"], [[1]])))
    r = await _post(client, "RETURN 1 AS x")
    assert r.status_code == 200
    assert [k for k, _ in drv.log] == ["execute_read", "tx.run"]
    assert drv.log[1][1] == "RETURN 1 AS x"


async def test_read_only_false_runs_auto_commit_and_returns_counters(admin, client, use_driver):
    drv = use_driver(FakeDriver(FakeResult([], [], FakeCounters(nodes_created=2, properties_set=3))))
    r = await _post(client, "CREATE (:Tag {name: 'a'})", read_only=False)
    assert r.status_code == 200
    assert [k for k, _ in drv.log] == ["session.run"]
    body = r.json()
    assert body["counters"]["nodes_created"] == 2 and body["counters"]["properties_set"] == 3
    assert body["rows"] == [] and body["nodes"] == []


async def test_neo4j_error_is_400_with_message(admin, client, use_driver):
    class Boom(Exception):
        message = "Writing in read access mode not allowed."

    use_driver(FakeDriver(error=Boom("raw")))
    r = await _post(client, "CREATE (n)")
    assert r.status_code == 400
    assert "read access mode" in r.json()["detail"]


# ── result shape ──────────────────────────────────────────────────────────────

async def test_scalar_rows(admin, client, use_driver):
    use_driver(FakeDriver(FakeResult(["title", "year"], [["A", 2020], ["B", None]])))
    body = (await _post(client, "MATCH (p) RETURN p.title AS title, p.year AS year")).json()
    assert body["columns"] == ["title", "year"]
    assert body["rows"] == [{"title": "A", "year": 2020}, {"title": "B", "year": None}]
    assert body["row_count"] == 2 and body["truncated"] is False
    assert body["nodes"] == [] and body["links"] == []
    assert isinstance(body["took_ms"], int)
    assert set(body["counters"]) == {
        "nodes_created", "nodes_deleted", "relationships_created",
        "relationships_deleted", "properties_set",
    }


async def test_nodes_and_relationships_feed_both_views(admin, client, use_driver):
    p = make_node("e1", ["Paper"], id="p1", title="Flow Matching", year=2022, raw_text="x" * 50)
    t = make_node("e2", ["Topic"], id="t1", name="Diffusion")
    r1 = make_rel("r1", "ABOUT", p, t)
    use_driver(FakeDriver(FakeResult(["p", "r", "t"], [[p, r1, t], [p, r1, t]])))
    body = (await _post(client, "MATCH (p)-[r]->(t) RETURN p, r, t")).json()

    # Table view: nodes carry their labels, relationships their type.
    assert body["rows"][0]["p"]["_labels"] == ["Paper"]
    assert body["rows"][0]["p"]["title"] == "Flow Matching"
    assert body["rows"][0]["r"] == {"_type": "ABOUT"}
    # Graph view: distinct nodes in the explorer format, one link despite two rows.
    by_id = {n["id"]: n for n in body["nodes"]}
    assert set(by_id) == {"p1", "t1"}
    assert by_id["p1"]["type"] == "paper" and by_id["p1"]["label"] == "Flow Matching"
    assert "raw_text" not in by_id["p1"]
    assert by_id["t1"]["type"] == "topic" and by_id["t1"]["label"] == "Diffusion"
    assert body["links"] == [{"source": "p1", "target": "t1", "type": "ABOUT"}]


async def test_paths_and_nested_values_are_extracted(admin, client, use_driver):
    a = make_node("pa", ["Paper"], id="a", title="A")
    b = make_node("pb", ["Paper"], id="b", title="B")
    c = make_node("pc", ["Person"], id="c", name="Cy")
    d = make_node("pd", ["Tag"], id="d", name="tg")
    r_ab = make_rel("rab", "CITES", a, b)
    r_bc = make_rel("rbc", "AUTHORED_BY", b, c)
    path = Path(a, r_ab, r_bc)
    nested = {"friends": [c, {"deep": d}], "n": 3}
    use_driver(FakeDriver(FakeResult(["path", "stuff"], [[path, nested]])))
    body = (await _post(client, "MATCH path=(a)-[*]->(c) RETURN path")).json()

    assert {n["id"] for n in body["nodes"]} == {"a", "b", "c", "d"}
    assert {(l["source"], l["target"], l["type"]) for l in body["links"]} == {
        ("a", "b", "CITES"), ("b", "c", "AUTHORED_BY"),
    }
    row = body["rows"][0]
    assert [n["id"] for n in row["path"]["_nodes"]] == ["a", "b", "c"]
    assert [r["_type"] for r in row["path"]["_relationships"]] == ["CITES", "AUTHORED_BY"]
    assert row["stuff"]["n"] == 3 and row["stuff"]["friends"][0]["name"] == "Cy"


async def test_node_without_id_property_falls_back_to_element_id(admin, client, use_driver):
    n = make_node("4:abc:7", ["Weird"], title="No id")
    use_driver(FakeDriver(FakeResult(["n"], [[n]])))
    body = (await _post(client)).json()
    assert body["nodes"][0]["id"] == "4:abc:7"
    assert body["nodes"][0]["type"] == "unknown"


async def test_relationship_alone_brings_its_end_points(admin, client, use_driver):
    a = make_node("ea", ["Paper"], id="a", title="A")
    b = make_node("eb", ["Paper"], id="b", title="B")
    rel = make_rel("rel1", "CITES", a, b)
    use_driver(FakeDriver(FakeResult(["r"], [[rel]])))
    body = (await _post(client, "MATCH ()-[r]->() RETURN r")).json()
    assert {n["id"] for n in body["nodes"]} == {"a", "b"}
    assert body["links"] == [{"source": "a", "target": "b", "type": "CITES"}]


# ── truncation ────────────────────────────────────────────────────────────────

async def test_rows_truncate_at_500(admin, client, use_driver):
    result = FakeResult(["i"], [[i] for i in range(600)])
    use_driver(FakeDriver(result))
    body = (await _post(client, "UNWIND range(0, 599) AS i RETURN i")).json()
    assert body["row_count"] == 500 and len(body["rows"]) == 500
    assert body["truncated"] is True
    assert body["rows"][-1] == {"i": 499}
    assert result.consumed is True


async def test_exactly_500_rows_is_not_truncated(admin, client, use_driver):
    use_driver(FakeDriver(FakeResult(["i"], [[i] for i in range(500)])))
    body = (await _post(client)).json()
    assert body["row_count"] == 500 and body["truncated"] is False


async def test_graph_view_keeps_nodes_beyond_the_row_cap(admin, client, use_driver):
    nodes = [make_node(f"e{i}", ["Tag"], id=f"t{i}", name=f"t{i}") for i in range(520)]
    use_driver(FakeDriver(FakeResult(["n"], [[n] for n in nodes])))
    body = (await _post(client)).json()
    assert body["row_count"] == 500 and body["truncated"] is True
    assert len(body["nodes"]) == 520


def test_collector_caps_nodes_and_drops_dangling_links():
    ns = [make_node(f"c{i}", ["Tag"], id=f"c{i}", name="x") for i in range(5)]
    rels = [make_rel(f"cr{i}", "RELATED_TO", ns[i], ns[i + 1]) for i in range(4)]
    col = GraphCollector(max_nodes=3)
    col.add(rels)
    nodes, links = col.result()
    assert [n["id"] for n in nodes] == ["c0", "c1", "c2"]
    assert links == [
        {"source": "c0", "target": "c1", "type": "RELATED_TO"},
        {"source": "c1", "target": "c2", "type": "RELATED_TO"},
    ]
    assert col.truncated is True and col.full is True


def test_serialize_value_temporal_and_collections():
    from neo4j.time import Date, DateTime

    out = serialize_value({"d": Date(2024, 5, 17), "t": DateTime(2024, 5, 17, 10, 0, 0), "s": {1}, "x": (1, 2)})
    assert out["d"] == "2024-05-17"
    assert out["t"].startswith("2024-05-17T10:00:00")
    assert out["s"] == [1] and out["x"] == [1, 2]


# ── against a real Neo4j (skipped when none is reachable) ──────────────────────

@pytest.fixture
def real_driver():
    try:
        drv = get_driver()
        drv.verify_connectivity()
    except Exception as exc:  # noqa: BLE001 — any connection problem means "skip"
        pytest.skip(f"Neo4j not reachable: {exc}")
    return drv


async def test_real_neo4j_read_only_rejects_writes(admin, client, real_driver):
    label = "GraphQueryProbe"
    try:
        r = await _post(client, f"CREATE (:{label} {{id: 'probe'}})")
        assert r.status_code == 400
        with real_driver.session() as s:
            assert s.run(f"MATCH (n:{label}) RETURN count(n) AS c").single()["c"] == 0

        r = await _post(client, f"CREATE (a:{label} {{id: 'probe'}})-[:LINKS]->(b:{label} {{id: 'probe2'}}) RETURN a, b", read_only=False)
        assert r.status_code == 200
        assert r.json()["counters"]["nodes_created"] == 2

        r = await _post(client, f"MATCH p=(a:{label})-[r]->(b) RETURN p, r")
        body = r.json()
        assert body["row_count"] == 1
        assert {n["id"] for n in body["nodes"]} == {"probe", "probe2"}
        assert body["links"] == [{"source": "probe", "target": "probe2", "type": "LINKS"}]
    finally:
        with real_driver.session() as s:
            s.run(f"MATCH (n:{label}) DETACH DELETE n").consume()
