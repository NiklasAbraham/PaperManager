import pytest
from db.connection import get_driver, close_driver


@pytest.mark.integration
def test_driver_connects():
    driver = get_driver()
    driver.verify_connectivity()


@pytest.mark.integration
def test_simple_cypher():
    driver = get_driver()
    with driver.session() as session:
        result = session.run("RETURN 1 AS n")
        record = result.single()
        assert record["n"] == 1
