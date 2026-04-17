from neo4j import Driver

_CONSTRAINTS = [
    "CREATE CONSTRAINT paper_id IF NOT EXISTS FOR (n:Paper) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT person_id IF NOT EXISTS FOR (n:Person) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT topic_id IF NOT EXISTS FOR (n:Topic) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT topic_name IF NOT EXISTS FOR (n:Topic) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT tag_id IF NOT EXISTS FOR (n:Tag) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT tag_name IF NOT EXISTS FOR (n:Tag) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT venue_id IF NOT EXISTS FOR (n:Venue) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT note_id IF NOT EXISTS FOR (n:Note) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT project_id IF NOT EXISTS FOR (n:Project) REQUIRE n.id IS UNIQUE",
]

_INDEXES = [
    """CREATE FULLTEXT INDEX paper_search IF NOT EXISTS
       FOR (n:Paper) ON EACH [n.title, n.abstract, n.summary]""",
    """CREATE FULLTEXT INDEX note_search IF NOT EXISTS
       FOR (n:Note) ON EACH [n.content]""",
]


def run_schema_setup(driver: Driver):
    with driver.session() as session:
        for stmt in _CONSTRAINTS + _INDEXES:
            session.run(stmt)
