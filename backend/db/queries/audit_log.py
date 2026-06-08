"""Audit log for tracking multi-user actions."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from neo4j import Driver


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_action(
    driver: Driver,
    username: str,
    action_type: str,
    entity_type: str,
    entity_id: str,
    details: dict | None = None,
) -> dict:
    """
    Log a user action to the audit trail.
    
    Args:
        driver: Neo4j driver
        username: User who performed the action
        action_type: Type of action (e.g., "create", "update", "delete", "add_member", "remove_member")
        entity_type: Type of entity affected (e.g., "project", "paper", "note", "project_member")
        entity_id: ID of the affected entity
        details: Optional dict with additional context
    """
    with driver.session() as session:
        result = session.run(
            """
            MATCH (u:User {name: $username})
            CREATE (log:AuditLog {
                id: $id,
                timestamp: $timestamp,
                username: $username,
                action_type: $action_type,
                entity_type: $entity_type,
                entity_id: $entity_id,
                details: $details
            })
            CREATE (u)-[:PERFORMED]->(log)
            RETURN log
            """,
            id=str(uuid.uuid4()),
            timestamp=_now(),
            username=username,
            action_type=action_type,
            entity_type=entity_type,
            entity_id=entity_id,
            details=str(details) if details else None,
        )
        return dict(result.single()["log"])


def get_audit_logs(
    driver: Driver,
    limit: int = 100,
    username: str | None = None,
    entity_type: str | None = None,
    action_type: str | None = None,
) -> list[dict]:
    """
    Retrieve audit logs with optional filtering.
    
    Args:
        driver: Neo4j driver
        limit: Maximum number of logs to return
        username: Optional filter by username
        entity_type: Optional filter by entity type
        action_type: Optional filter by action type
    """
    filters = []
    params = {"limit": limit}
    
    if username:
        filters.append("log.username = $username")
        params["username"] = username
    if entity_type:
        filters.append("log.entity_type = $entity_type")
        params["entity_type"] = entity_type
    if action_type:
        filters.append("log.action_type = $action_type")
        params["action_type"] = action_type
    
    where_clause = "WHERE " + " AND ".join(filters) if filters else ""
    
    with driver.session() as session:
        result = session.run(
            f"""
            MATCH (log:AuditLog)
            {where_clause}
            RETURN log
            ORDER BY log.timestamp DESC
            LIMIT $limit
            """,
            **params
        )
        return [dict(r["log"]) for r in result]


def get_user_activity_feed(driver: Driver, username: str, limit: int = 50) -> list[dict]:
    """Get a user's recent activity feed."""
    with driver.session() as session:
        result = session.run(
            """
            MATCH (u:User {name: $username})-[:PERFORMED]->(log:AuditLog)
            RETURN log
            ORDER BY log.timestamp DESC
            LIMIT $limit
            """,
            username=username,
            limit=limit,
        )
        return [dict(r["log"]) for r in result]


def get_entity_history(driver: Driver, entity_id: str, limit: int = 50) -> list[dict]:
    """Get the audit history for a specific entity."""
    with driver.session() as session:
        result = session.run(
            """
            MATCH (log:AuditLog {entity_id: $entity_id})
            RETURN log
            ORDER BY log.timestamp DESC
            LIMIT $limit
            """,
            entity_id=entity_id,
            limit=limit,
        )
        return [dict(r["log"]) for r in result]
