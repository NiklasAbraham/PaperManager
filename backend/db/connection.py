import logging
from neo4j import GraphDatabase, Driver
from neo4j.exceptions import ServiceUnavailable, SessionExpired
from config import settings

log = logging.getLogger(__name__)

_driver: Driver | None = None


def _create_driver() -> Driver:
    return GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
        # Keep connections alive and allow the driver to re-route after a dropped connection
        max_connection_lifetime=1800,       # close connections older than 30 min (before Aura kills them)
        keep_alive=True,
        connection_acquisition_timeout=30,
    )


def get_driver() -> Driver:
    global _driver
    if _driver is None:
        _driver = _create_driver()
    return _driver


def reset_driver():
    """Close the current driver and create a fresh one. Called after connection errors."""
    global _driver
    if _driver is not None:
        try:
            _driver.close()
        except Exception:
            pass
    _driver = _create_driver()
    log.info("Neo4j driver reconnected")
    return _driver


def close_driver():
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None
