"""Pure tests for the dashboard helpers (week bucketing, tag filtering)."""
from datetime import datetime, timezone

from services import topic_map as tm

NOW = datetime(2026, 11, 12, 15, 0, tzinfo=timezone.utc)   # a Thursday


def test_twelve_weeks_zero_filled_monday_starts():
    out = tm.week_buckets([], NOW)
    assert len(out) == 12
    assert out[-1]["week_start"] == "2026-11-09"
    assert out[0]["week_start"] == "2026-08-24"
    assert all(datetime.fromisoformat(w["week_start"]).weekday() == 0 for w in out)
    assert all(w["count"] == 0 for w in out)


def test_counts_land_in_the_right_week():
    created = ["2026-11-09T00:00:00+00:00", "2026-11-12T10:00:00+00:00", "2026-11-08T23:59:59+00:00",
               "2026-08-24T05:00:00+00:00", "2026-08-23T23:00:00+00:00",   # the last is before the window
               "2026-11-10T08:00:00Z", None, "garbage"]
    out = {w["week_start"]: w["count"] for w in tm.week_buckets(created, NOW)}
    assert out["2026-11-09"] == 3
    assert out["2026-11-02"] == 1
    assert out["2026-08-24"] == 1
    assert sum(out.values()) == 5


def test_naive_timestamps_and_year_boundary():
    now = datetime(2027, 1, 2, tzinfo=timezone.utc)          # Saturday
    out = tm.week_buckets(["2026-12-28T12:00:00"], now)
    assert out[-1]["week_start"] == "2026-12-28"
    assert out[-1]["count"] == 1 and len(out) == 12


def test_system_tags():
    assert tm.is_system_tag("from-references") and tm.is_system_tag("from-arxiv") and tm.is_system_tag("pdf-upload")
    assert not tm.is_system_tag("protein-design")


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def single(self):
        return self._rows[0]

    def value(self):
        return [next(iter(r.values())) for r in self._rows]

    def data(self):
        return self._rows


class _FakeSession:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, query, **params):
        if "AS total" in query:
            return _FakeResult([{"total": 10, "added_7d": 2, "added_30d": 5, "read": 3, "reading": 1}])
        if "AS c" in query and "created_at >= $since" not in query:
            return _FakeResult([{"c": 4}])
        return _FakeResult([])


class _FakeDriver:
    def session(self):
        return _FakeSession()


def test_dashboard_for_a_non_admin_user(monkeypatch):
    """Paper and project visibility clauses share the vis_user parameter; passing both must not fail."""
    from routers import stats
    monkeypatch.setattr("db.queries.visibility.current_user", lambda: "alice")
    out = stats._dashboard(_FakeDriver(), now=datetime(2026, 11, 12, tzinfo=timezone.utc))
    assert out["total"] == 10 and out["references"] == 4
    assert out["reading"] == {"unread": 6, "reading": 1, "read": 3}
    assert len(out["added_weekly"]) == 12
