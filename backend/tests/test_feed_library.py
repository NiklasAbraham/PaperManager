"""The library query of the feed: visibility, parameters, and which signals count for whom."""
from __future__ import annotations

from services.auth import reset_request_user, set_request_user
from services.feed import library, ranking


class Rec:
    """A driver that records the Cypher it is given and answers with fixed rows."""

    def __init__(self, rows, n_users):
        self.rows, self.n_users, self.queries = rows, n_users, []

    def session(self):
        outer = self

        class S:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def run(self, query, **params):
                outer.queries.append((query, params))
                if "count(u)" in query:
                    class One:
                        def single(_):
                            return {"n": outer.n_users}
                    return One()
                return outer.rows

        return S()


ROW = {"id": "p1", "title": "T", "doi": None, "rating": 5, "bookmarked": None, "status": "read",
       "created_at": "2026-01-01", "highlights": 2, "mine": True}


def test_query_applies_visibility_and_passes_names_as_parameters():
    tok = set_request_user("alice")
    try:
        drv = Rec([ROW], 1)
        rows, single = library.visible_papers(drv, "al'ice\"; MATCH (n) DETACH DELETE n //")
    finally:
        reset_request_user(tok)
    q, params = drv.queries[0]
    assert "IN_PROJECT" in q and "MEMBER_OF" in q                  # the visibility clause for a non-admin
    assert params["vis_user"] == "alice"
    assert params["feed_user"] == "al'ice\"; MATCH (n) DETACH DELETE n //"
    assert "DETACH DELETE" not in q and "al'ice" not in q
    assert rows == [ROW] and single is True
    assert params["ref_tag"] == "from-references"
    assert "{name: $ref_tag}" in q and "IN_PROJECT" in q and "ADDED" in q and "has_text" in q
    assert "from-references" not in q and "'" not in q.replace("''", "")      # no literal values in the text


def test_admin_sees_everything_and_user_count_decides_single_user(monkeypatch):
    monkeypatch.setattr("db.queries.visibility.ADMIN_USERNAME", "root")
    tok = set_request_user("root")
    try:
        drv = Rec([ROW], 3)
        rows, single = library.visible_papers(drv, "root")
    finally:
        reset_request_user(tok)
    assert single is False and "MEMBER_OF" not in drv.queries[0][0]
    drv = Rec([ROW], 0)
    assert library.visible_papers(drv, "x")[1] is True            # no user nodes yet: single


def test_shared_signals_count_only_for_papers_the_user_added_on_multi_user_instances():
    rows = [dict(ROW, id="a", mine=True), dict(ROW, id="b", mine=False), dict(ROW, id="c", rating=1, mine=True)]
    pos, neg = ranking._entries(rows, single_user=False, labels={})
    assert [p[0] for p in pos] == ["a"] and [n[0] for n in neg] == ["c"]
    pos, neg = ranking._entries(rows, single_user=True, labels={})
    assert [p[0] for p in pos] == ["a", "b"]


def test_kept_signal_is_the_max_not_the_sum_and_needs_a_real_paper():
    base = dict(ROW, rating=None, status="unread", highlights=0, bookmarked=None, has_text=True, stub=False,
                mine=False, in_project=False)
    rows = [
        dict(base, id="added", mine=True),
        dict(base, id="project", in_project=True),
        dict(base, id="both", mine=True, in_project=True),                       # still 0.3, not 0.6
        dict(base, id="both_read", mine=True, in_project=True, rating=3, status="read"),   # 0.5 wins
        dict(base, id="rated5", mine=True, in_project=True, rating=5),            # 1.0 wins
        dict(base, id="rated1", mine=True, in_project=True, rating=1),            # an explicit no stays a no
        dict(base, id="stub", mine=True, stub=True),
        dict(base, id="bare", mine=True, has_text=False),
        dict(base, id="foreign"),
    ]
    pos, neg = ranking._entries(rows, single_user=False, labels={})
    assert {p[0]: p[2] for p in pos} == {"added": 0.3, "project": 0.3, "both": 0.3, "both_read": 0.5, "rated5": 1.0}
    assert [n[0] for n in neg] == ["rated1"]
    # global signals of another user's paper do not leak, but the kept signal of mine / my project stands
    rows = [dict(base, id="x", rating=5, in_project=True)]
    pos, _ = ranking._entries(rows, single_user=False, labels={})
    assert [(p[0], p[2]) for p in pos] == [("x", 0.3)]


def test_feed_labels_always_count_and_map_to_signs():
    pos, neg = ranking._entries([], single_user=False, labels={"c1": (1, "t1"), "c2": (-1, "t2"), "c3": (0, "t3")})
    assert [p[0] for p in pos] == ["c1"] and [n[0] for n in neg] == ["c2", "c3"]
