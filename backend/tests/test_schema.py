import pytest
from db.connection import get_driver, close_driver
from db.schema import run_schema_setup


@pytest.mark.integration
def test_schema_setup_idempotent():
    driver = get_driver()
    # Run twice — must not raise
    run_schema_setup(driver)
    run_schema_setup(driver)


@pytest.mark.integration
def test_constraints_exist():
    driver = get_driver()
    run_schema_setup(driver)
    with driver.session() as session:
        result = session.run("SHOW CONSTRAINTS")
        names = {r["name"] for r in result}
    expected = {
        "paper_id", "person_id", "topic_id", "topic_name",
        "tag_id", "tag_name", "venue_id", "note_id", "project_id",
    }
    assert expected.issubset(names), f"Missing constraints: {expected - names}"


@pytest.mark.integration
def test_indexes_exist():
    driver = get_driver()
    run_schema_setup(driver)
    with driver.session() as session:
        result = session.run("SHOW INDEXES")
        names = {r["name"] for r in result}
    assert "paper_search" in names
    assert "note_search" in names
