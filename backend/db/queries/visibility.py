"""Reusable visibility / access-control helpers for project-scoped data.

Access rules (see product decision):
- Projects: a user only sees projects they are a member of (MEMBER_OF).
- Papers: a user sees papers that are not assigned to any project (the shared
  global library) plus papers in a project they are a member of.
- The admin user "niklas" bypasses all restrictions and sees everything.

The current user is read from the request-scoped context var populated by the
auth middleware (services.auth.get_request_user), so these helpers work inside
query functions without threading the username through every call site.
"""
from __future__ import annotations

from neo4j import Driver

from services.auth import get_request_user

ADMIN_USERNAME = "niklas"


def current_user() -> str | None:
    """Return the username of the requester (or None outside request scope)."""
    return get_request_user()


def is_admin(username: str | None) -> bool:
    """Only the dedicated admin account bypasses visibility filters."""
    return bool(username) and username.strip().lower() == ADMIN_USERNAME


def paper_visibility_clause(var: str = "p") -> tuple[str, dict]:
    """Return a Cypher boolean expression restricting Paper `var` to the papers
    the current user may see, plus the parameters it references.

    Use it inside a WHERE clause. Admins get an always-true expression.
    """
    user = current_user()
    if is_admin(user):
        return "true", {}
    clause = (
        f"(NOT EXISTS {{ ({var})-[:IN_PROJECT]->(:Project) }} "
        f"OR EXISTS {{ MATCH ({var})-[:IN_PROJECT]->(:Project)<-[:MEMBER_OF]-(_mu:User) "
        f"WHERE toLower(_mu.name) = toLower($vis_user) }})"
    )
    return clause, {"vis_user": user or ""}


def project_visibility_clause(var: str = "proj") -> tuple[str, dict]:
    """Return a Cypher boolean restricting Project `var` to ones the current
    user is a member of, plus the parameters it references."""
    user = current_user()
    if is_admin(user):
        return "true", {}
    clause = (
        f"EXISTS {{ MATCH ({var})<-[:MEMBER_OF]-(_mu:User) "
        f"WHERE toLower(_mu.name) = toLower($vis_user) }}"
    )
    return clause, {"vis_user": user or ""}


def node_visibility_clause(var: str) -> tuple[str, dict]:
    """Return a Cypher boolean that hides Paper/Project nodes the current user
    may not see, while allowing all other node types. For graph queries."""
    user = current_user()
    if is_admin(user):
        return "true", {}
    paper_c, _ = paper_visibility_clause(var)
    proj_c, _ = project_visibility_clause(var)
    clause = f"((NOT {var}:Paper OR {paper_c}) AND (NOT {var}:Project OR {proj_c}))"
    return clause, {"vis_user": user or ""}


def can_see_paper(driver: Driver, paper_id: str) -> bool:
    """Whether the current user may view a specific paper."""
    user = current_user()
    if is_admin(user):
        return True
    clause, params = paper_visibility_clause("p")
    with driver.session() as session:
        rec = session.run(
            f"MATCH (p:Paper {{id: $id}}) RETURN ({clause}) AS ok",
            id=paper_id,
            **params,
        ).single()
    return bool(rec and rec["ok"])


def can_see_project(driver: Driver, project_id: str) -> bool:
    """Whether the current user may view a specific project."""
    user = current_user()
    if is_admin(user):
        return True
    clause, params = project_visibility_clause("proj")
    with driver.session() as session:
        rec = session.run(
            f"MATCH (proj:Project {{id: $id}}) RETURN ({clause}) AS ok",
            id=project_id,
            **params,
        ).single()
    return bool(rec and rec["ok"])
