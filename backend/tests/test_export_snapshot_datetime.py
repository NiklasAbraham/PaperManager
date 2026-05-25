import json
import datetime
import pytest
from routers.export import export_snapshot, _json_safe

class DummyDriver:
    def session(self):
        class S:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def run(self, query):
                q = " ".join(query.split())
                if "MATCH (n) RETURN elementId(n) AS export_id" in q:
                    return [{
                        "export_id": "n1",
                        "labels": ["Test"],
                        "props": {"id": "n1", "created": datetime.datetime(2024, 5, 24, 12, 0, 0)}
                    }]
                if "MATCH (a)-[r]->(b) RETURN elementId(r) AS export_id" in q:
                    return []
                raise AssertionError(query)
        return S()

def test_json_safe_datetime():
    dt = datetime.datetime(2024, 5, 24, 12, 0, 0)
    assert _json_safe(dt) == "2024-05-24T12:00:00"

@pytest.mark.asyncio
async def test_export_snapshot_with_datetime():
    response = export_snapshot(driver=DummyDriver())
    data = json.loads(response.body.decode("utf-8"))
    assert data["nodes"][0]["properties"]["created"] == "2024-05-24T12:00:00"
