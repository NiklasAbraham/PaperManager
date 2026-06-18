from unittest.mock import patch

from db.queries.papers import find_duplicate, merge_reference_stubs_into_paper


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def single(self):
        return self._rows[0] if self._rows else None

    def data(self):
        return self._rows

    def __iter__(self):
        return iter(self._rows)


class _FakeSession:
    def __init__(self, driver):
        self._driver = driver
        self._responses = driver._responses

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def run(self, _query, **_params):
        idx = self._driver.calls
        self._driver.calls += 1
        if idx >= len(self._responses):
            return _FakeResult([])
        return _FakeResult(self._responses[idx])


class _FakeDriver:
    def __init__(self, responses):
        self._responses = responses
        self.calls = 0

    def session(self):
        return _FakeSession(self)


def test_find_duplicate_prefers_existing_full_paper_for_exact_title_match():
    driver = _FakeDriver([
        [
            {"p": {"id": "ref-1", "title": "Sample Paper", "drive_file_id": None}},
            {"p": {"id": "paper-1", "title": "Sample Paper", "drive_file_id": "drive-123"}},
        ]
    ])

    found = find_duplicate(driver, title="Sample Paper")

    assert found is not None
    assert found["id"] == "paper-1"
    assert found["drive_file_id"] == "drive-123"


def test_find_duplicate_prefers_existing_full_paper_for_normalized_title_match():
    driver = _FakeDriver([
        [],
        [
            {"p": {"id": "ref-1", "title": "A Study on Test Cases", "drive_file_id": None}},
            {"p": {"id": "paper-1", "title": "A Study on Test Cases!", "drive_file_id": "drive-123"}},
        ],
    ])

    found = find_duplicate(driver, title="A study on test cases!")

    assert found is not None
    assert found["id"] == "paper-1"
    assert found["drive_file_id"] == "drive-123"


def test_merge_reference_stubs_into_paper_merges_unique_stub_ids():
    driver = _FakeDriver([
        [
            {"id": "stub-1"},
            {"id": "stub-2"},
        ],
        [
            {"id": "stub-1", "title": "Sample Paper"},
            {"id": "stub-3", "title": "Sample Paper!"},
            {"id": "other", "title": "Different Title"},
        ],
    ])

    with patch("db.queries.papers._merge_paper_into_keep", side_effect=[2, 4, 1]) as mock_merge:
        moved = merge_reference_stubs_into_paper(
            driver,
            keep_id="paper-1",
            doi="10.1000/sample",
            title="Sample Paper",
        )

    assert moved == 7
    assert mock_merge.call_count == 3
    mock_merge.assert_any_call(driver, "paper-1", "stub-1")
    mock_merge.assert_any_call(driver, "paper-1", "stub-2")
    mock_merge.assert_any_call(driver, "paper-1", "stub-3")
