import uuid
from datetime import datetime, timezone
from neo4j import Driver


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_project(driver: Driver, data: dict) -> dict:
    props = {
        "id": str(uuid.uuid4()),
        "name": data.get("name", ""),
        "description": data.get("description"),
        "status": data.get("status", "active"),
        "created_at": _now(),
        "updated_at": _now(),
    }
    with driver.session() as session:
        result = session.run("CREATE (p:Project $props) RETURN p", props=props)
        return dict(result.single()["p"])


def get_project(driver: Driver, project_id: str) -> dict | None:
    with driver.session() as session:
        result = session.run("MATCH (p:Project {id: $id}) RETURN p", id=project_id)
        record = result.single()
        return dict(record["p"]) if record else None


def list_projects(driver: Driver) -> list[dict]:
    with driver.session() as session:
        result = session.run(
            """
            MATCH (proj:Project)
            OPTIONAL MATCH (p:Paper)-[:IN_PROJECT]->(proj)
            RETURN proj, count(p) AS paper_count
            ORDER BY proj.created_at DESC
            """
        )
        return [{**dict(r["proj"]), "paper_count": r["paper_count"]} for r in result]


def update_project(driver: Driver, project_id: str, data: dict) -> dict | None:
    data["updated_at"] = _now()
    with driver.session() as session:
        result = session.run(
            "MATCH (p:Project {id: $id}) SET p += $props RETURN p",
            id=project_id,
            props=data,
        )
        record = result.single()
        return dict(record["p"]) if record else None


def delete_project(driver: Driver, project_id: str) -> bool:
    with driver.session() as session:
        result = session.run(
            "MATCH (p:Project {id: $id}) DETACH DELETE p RETURN count(p) AS deleted",
            id=project_id,
        )
        return result.single()["deleted"] > 0


def add_paper_to_project(driver: Driver, paper_id: str, project_id: str):
    with driver.session() as session:
        session.run(
            """
            MATCH (p:Paper {id: $pid}), (proj:Project {id: $projid})
            MERGE (p)-[:IN_PROJECT]->(proj)
            """,
            pid=paper_id,
            projid=project_id,
        )


def remove_paper_from_project(driver: Driver, paper_id: str, project_id: str):
    with driver.session() as session:
        session.run(
            """
            MATCH (p:Paper {id: $pid})-[r:IN_PROJECT]->(proj:Project {id: $projid})
            DELETE r
            """,
            pid=paper_id,
            projid=project_id,
        )


def get_project_papers(driver: Driver, project_id: str) -> list[dict]:
    with driver.session() as session:
        result = session.run(
            """
            MATCH (p:Paper)-[:IN_PROJECT]->(proj:Project {id: $id})
            OPTIONAL MATCH (u:User)-[:ADDED]->(p)
            WITH p, head(collect(u)) AS added_user
            RETURN p, added_user.name AS added_by, added_user.color AS added_by_color
            ORDER BY p.created_at DESC
            """,
            id=project_id,
        )
        rows: list[dict] = []
        for r in result:
            d = dict(r["p"])
            d["added_by"] = r["added_by"]
            d["added_by_color"] = r["added_by_color"]
            rows.append(d)
        return rows


def link_projects(driver: Driver, project_a_id: str, project_b_id: str):
    with driver.session() as session:
        session.run(
            """
            MATCH (a:Project {id: $aid}), (b:Project {id: $bid})
            MERGE (a)-[:RELATED_TO]-(b)
            """,
            aid=project_a_id,
            bid=project_b_id,
        )


# ── Project Membership & Roles ────────────────────────────────────────────────


def add_project_member(driver: Driver, project_id: str, user_name: str, role: str = "read") -> dict:
    """
    Add a user to a project with a specific role.
    Role can be: 'read', 'write', or 'admin'.
    Returns the created relationship properties.
    """
    with driver.session() as session:
        result = session.run(
            """
            MATCH (proj:Project {id: $pid})
            MERGE (u:User {name: $name})
            ON CREATE SET u.id = $uid, u.created_at = $now
            MERGE (u)-[m:MEMBER_OF]->(proj)
            ON CREATE SET m.role = $role, m.joined_at = $now
            ON MATCH SET m.role = $role, m.updated_at = $now
            RETURN m, u.name AS username
            """,
            pid=project_id,
            name=user_name,
            uid=str(uuid.uuid4()),
            role=role,
            now=_now(),
        )
        rec = result.single()
        if not rec:
            raise ValueError("Project not found")
        rel = dict(rec["m"])
        rel["username"] = rec["username"]
        return rel


def remove_project_member(driver: Driver, project_id: str, user_name: str) -> bool:
    """Remove a user from a project. Returns True if a membership was deleted."""
    with driver.session() as session:
        result = session.run(
            """
            MATCH (u:User {name: $name})-[m:MEMBER_OF]->(proj:Project {id: $pid})
            DELETE m
            RETURN count(m) AS deleted
            """,
            name=user_name,
            pid=project_id,
        )
        return result.single()["deleted"] > 0


def get_project_members(driver: Driver, project_id: str) -> list[dict]:
    """Return all members of a project with their roles."""
    with driver.session() as session:
        result = session.run(
            """
            MATCH (u:User)-[m:MEMBER_OF]->(proj:Project {id: $pid})
            RETURN u.name AS username,
                   u.id AS user_id,
                   u.color AS color,
                   m.role AS role,
                   m.joined_at AS joined_at,
                   m.updated_at AS updated_at
            ORDER BY m.joined_at ASC
            """,
            pid=project_id,
        )
        return [dict(r) for r in result]


def get_user_project_role(driver: Driver, project_id: str, user_name: str) -> str | None:
    """Return the role of a user in a project, or None if not a member."""
    with driver.session() as session:
        result = session.run(
            """
            MATCH (u:User {name: $name})-[m:MEMBER_OF]->(proj:Project {id: $pid})
            RETURN m.role AS role
            """,
            name=user_name,
            pid=project_id,
        ).single()
        return result["role"] if result else None


def list_user_projects(driver: Driver, user_name: str) -> list[dict]:
    """Return all projects a user is a member of."""
    with driver.session() as session:
        result = session.run(
            """
            MATCH (u:User {name: $name})-[m:MEMBER_OF]->(proj:Project)
            OPTIONAL MATCH (p:Paper)-[:IN_PROJECT]->(proj)
            WITH proj, m.role AS role, count(p) AS paper_count
            RETURN proj, role, paper_count
            ORDER BY proj.created_at DESC
            """,
            name=user_name,
        )
        return [{**dict(r["proj"]), "role": r["role"], "paper_count": r["paper_count"]} for r in result]
