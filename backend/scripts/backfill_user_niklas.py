"""
One-time migration: attribute all existing Papers, Notes, and Conversations
to user "Niklas".

Run from the project root:
    /Users/you/miniforge3/envs/papermanager/bin/python backend/scripts/backfill_user_niklas.py
"""
import sys
from pathlib import Path

# Allow imports from backend/
sys.path.insert(0, str(Path(__file__).parent.parent))

from db.connection import get_driver  # noqa: E402 — after sys.path setup

USER_NAME = "Niklas"


def run():
    driver = get_driver()
    with driver.session() as session:
        # Create user node
        session.run(
            """
            MERGE (u:User {name: $name})
            ON CREATE SET u.id = randomUUID(), u.created_at = datetime()
            """,
            name=USER_NAME,
        )
        print(f"User '{USER_NAME}' ensured.")

        # Attribute all Papers that don't already have an ADDED relationship
        r = session.run(
            """
            MATCH (p:Paper)
            WHERE NOT ((:User)-[:ADDED]->(p))
            MATCH (u:User {name: $name})
            MERGE (u)-[:ADDED]->(p)
            RETURN count(p) AS n
            """,
            name=USER_NAME,
        ).single()
        print(f"Papers attributed: {r['n']}")

        # Attribute all Notes
        r = session.run(
            """
            MATCH (n:Note)
            WHERE NOT ((:User)-[:WROTE]->(n))
            MATCH (u:User {name: $name})
            MERGE (u)-[:WROTE]->(n)
            RETURN count(n) AS n
            """,
            name=USER_NAME,
        ).single()
        print(f"Notes attributed: {r['n']}")

        # Attribute all Conversations
        r = session.run(
            """
            MATCH (c:Conversation)
            WHERE NOT ((:User)-[:STARTED]->(c))
            MATCH (u:User {name: $name})
            MERGE (u)-[:STARTED]->(c)
            RETURN count(c) AS n
            """,
            name=USER_NAME,
        ).single()
        print(f"Conversations attributed: {r['n']}")

    driver.close()
    print("Done.")


if __name__ == "__main__":
    run()
