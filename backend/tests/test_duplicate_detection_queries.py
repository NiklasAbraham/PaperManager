from db.queries.papers import find_duplicate


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def single(self):
        return self._rows[0] if self._rows else None

    def data(self):
        return self._rows


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
