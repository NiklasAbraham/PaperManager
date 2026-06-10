from db.queries.papers import list_papers, get_paper, update_paper
from db.queries.projects import get_project_papers


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)

    def single(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def run(self, _query, **_params):
        return _FakeResult(self._rows)


class _FakeDriver:
    def __init__(self, rows):
        self._rows = rows

    def session(self):
        return _FakeSession(self._rows)


def test_list_papers_includes_added_by_metadata():
    driver = _FakeDriver([
        {"p": {"id": "p1", "title": "Paper 1"}, "added_by": "Niklas", "added_by_color": "#7c3aed"},
        {"p": {"id": "p2", "title": "Paper 2"}, "added_by": None, "added_by_color": None},
    ])

    rows = list_papers(driver)

    assert rows[0]["added_by"] == "Niklas"
    assert rows[0]["added_by_color"] == "#7c3aed"
    assert rows[1]["added_by"] is None
    assert rows[1]["added_by_color"] is None


def test_get_paper_includes_added_by_metadata():
    driver = _FakeDriver([
        {"p": {"id": "p1", "title": "Paper 1"}, "added_by": "Jan", "added_by_color": "#2563eb"}
    ])

    row = get_paper(driver, "p1")

    assert row is not None
    assert row["added_by"] == "Jan"
    assert row["added_by_color"] == "#2563eb"


def test_get_project_papers_includes_added_by_metadata():
    driver = _FakeDriver([
        {"p": {"id": "p1", "title": "Paper 1"}, "added_by": "Niklas", "added_by_color": "#7c3aed"}
    ])

    rows = get_project_papers(driver, "proj-1")

    assert rows == [
        {"id": "p1", "title": "Paper 1", "added_by": "Niklas", "added_by_color": "#7c3aed"}
    ]


def test_update_paper_includes_added_by_metadata():
    driver = _FakeDriver([
        {"p": {"id": "p1", "title": "Paper 1"}, "added_by": "Niklas", "added_by_color": "#7c3aed"}
    ])

    row = update_paper(driver, "p1", {"reading_status": "reading"})

    assert row == {"id": "p1", "title": "Paper 1", "added_by": "Niklas", "added_by_color": "#7c3aed"}
