# pythonpath = . in pytest.ini handles path setup

import os

# The endpoint tests drive the app through httpx's ASGI transport with
# base_url="http://test", so the request Host header is "test". The app wraps
# itself in TrustedHostMiddleware (default allowed hosts: localhost,127.0.0.1),
# which would reject that Host with "400 Invalid host header". Allow the test
# host here before main/config is imported. setdefault keeps any real
# environment override (e.g. CI) intact.
os.environ.setdefault("TRUSTED_HOSTS", "localhost,127.0.0.1,test,testserver")
# Most endpoint tests call the API without a session; test_route_guards.py turns the
# login requirement back on for its own checks.
os.environ.setdefault("REQUIRE_LOGIN", "false")
# Extracted references have their DOIs / arXiv ids resolved online (services/citecheck.py);
# off in tests, test_citecheck.py turns it on with the resolvers patched.
os.environ.setdefault("REFERENCE_ID_CHECK", "0")


# Many tests create and delete real nodes through get_driver(). Run against anything but a
# local, throwaway Neo4j they leave test papers, notes and projects in a real library (this
# happened when the suite was run inside the production backend container). Refuse unless
# the database is on this machine, or PM_TESTS_ALLOW_DB=1 says it is disposable.
def pytest_configure(config):
    from urllib.parse import urlparse

    from config import settings

    host = urlparse(settings.neo4j_uri).hostname or ""
    if host not in {"", "localhost", "127.0.0.1", "::1"} and os.environ.get("PM_TESTS_ALLOW_DB") != "1":
        import pytest

        pytest.exit(
            f"Refusing to run tests against the Neo4j at '{host}': tests write to the database. "
            "Point NEO4J_URI at a throwaway local Neo4j, or set PM_TESTS_ALLOW_DB=1 if it is disposable.",
            returncode=2,
        )


import pytest


@pytest.fixture(scope="session", autouse=True)
def _neo4j_schema():
    """Create the constraints and fulltext indexes once per run and wait until they are
    online. The app does this in its lifespan, which the ASGI test client never runs, so on
    a fresh test database the search tests otherwise race the index creation. Runs that use
    only the in-memory fake driver (no Neo4j reachable) skip this."""
    from db.connection import get_driver

    try:
        driver = get_driver()
        driver.verify_connectivity()
    except Exception:  # noqa: BLE001 — no database: nothing to set up
        yield
        return
    from db.schema import run_schema_setup

    run_schema_setup(driver)
    with driver.session() as session:
        session.run("CALL db.awaitIndexes(120)").consume()
    yield


@pytest.fixture(autouse=True)
def _no_external_network(request, monkeypatch):
    """Fail any test (except @integration ones) that tries to reach a host other than the
    test Neo4j. The lookup is refused as if offline, so code that swallows network errors
    as "best effort" cannot hide the attempt, and the test fails at teardown naming the host."""
    if request.node.get_closest_marker("integration"):
        yield
        return
    import socket
    from urllib.parse import urlparse

    from config import settings

    allowed = {"localhost", "127.0.0.1", "::1", "test", "testserver", urlparse(settings.neo4j_uri).hostname}
    real_getaddrinfo = socket.getaddrinfo
    attempts: list[str] = []

    def guarded_getaddrinfo(host, *args, **kwargs):
        name = host.decode() if isinstance(host, bytes) else host
        if name is None or name in allowed:
            return real_getaddrinfo(host, *args, **kwargs)
        attempts.append(name)
        raise socket.gaierror(socket.EAI_NONAME, f"external network is blocked in tests: {name}")

    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
    yield
    if attempts:
        pytest.fail(f"Test tried to reach external hosts: {sorted(set(attempts))}. Mock the call "
                    "or mark the test @pytest.mark.integration.", pytrace=False)


# ── Demo library ──────────────────────────────────────────────────────────────
# A populated graph of ~10 well-known papers (tests/fixtures/demo_library.json, loaded by
# tests/demo_data.py). Both fixtures empty the test database first and again afterwards, so
# tests that use them see exactly the demo library and leave nothing behind, whatever ran
# before. pytest_configure above has already refused any database that is not disposable.

def _wipe_test_database(driver) -> None:
    with driver.session() as session:
        session.run("MATCH (n) DETACH DELETE n").consume()


def _fresh_demo_library():
    from db.connection import get_driver
    from tests.demo_data import load_demo_library

    driver = get_driver()
    _wipe_test_database(driver)
    return driver, load_demo_library(driver)


@pytest.fixture(scope="module")
def demo_library():
    """The demo library, loaded once per test module. Tests must not change it;
    use demo_library_fresh for tests that write."""
    driver, ids = _fresh_demo_library()
    yield ids
    _wipe_test_database(driver)


@pytest.fixture
def demo_library_fresh():
    """The demo library, loaded for one test, which may change it."""
    driver, ids = _fresh_demo_library()
    yield ids
    _wipe_test_database(driver)


@pytest.fixture
def auth_headers():
    """Authorization headers for a username: auth_headers("demo_alice")."""
    from services.auth import create_access_token

    return lambda user: {"Authorization": f"Bearer {create_access_token({'sub': user})}"}
