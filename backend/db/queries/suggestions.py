"""Suggestion nodes (.specs/015_suggestions.md): ideas for improving PaperManager itself.

``(:Suggestion {id, text, detail, source, status, created_by, created_at, updated_at,
voters, context, conversation_id, seen})``. They are shared by every user of the instance.
Callers use the functions as module attributes (``sq.list_suggestions(...)``) so tests can
swap them for an in-memory fake.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from neo4j import Driver

STATUSES = ("open", "planned", "done", "dismissed")
SOURCES = ("chat", "user", "report")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row(record: Any) -> dict | None:
    return dict(record["s"]) if record else None


def create_suggestion(
    driver: Driver,
    *,
    text: str,
    source: str,
    created_by: str,
    detail: str = "",
    context: str = "",
    conversation_id: str | None = None,
) -> dict:
    """Create an open suggestion; the creator's vote is added."""
    now = _now()
    with driver.session() as session:
        record = session.run(
            """
            CREATE (s:Suggestion {
                id: $id, text: $text, detail: $detail, source: $source, status: 'open',
                created_by: $created_by, created_at: $now, updated_at: $now,
                voters: $voters, context: $context, conversation_id: $conversation_id, seen: 1
            })
            RETURN s
            """,
            id=str(uuid.uuid4()),
            text=text,
            detail=detail,
            source=source,
            created_by=created_by,
            now=now,
            voters=[created_by] if created_by else [],
            context=context,
            conversation_id=conversation_id,
        ).single()
        return _row(record)  # type: ignore[return-value]


def list_suggestions(driver: Driver, status: str | None = None, source: str | None = None) -> list[dict]:
    """All suggestions matching the optional filters, in no particular order."""
    with driver.session() as session:
        result = session.run(
            """
            MATCH (s:Suggestion)
            WHERE ($status IS NULL OR s.status = $status) AND ($source IS NULL OR s.source = $source)
            RETURN s
            """,
            status=status,
            source=source,
        )
        return [dict(r["s"]) for r in result]


def counts(driver: Driver) -> dict[str, int]:
    """Number of suggestions per status (all four keys present)."""
    out = {s: 0 for s in STATUSES}
    with driver.session() as session:
        for r in session.run("MATCH (s:Suggestion) RETURN s.status AS status, count(s) AS n"):
            if r["status"] in out:
                out[r["status"]] = r["n"]
    return out


def get_suggestion(driver: Driver, suggestion_id: str) -> dict | None:
    with driver.session() as session:
        return _row(session.run("MATCH (s:Suggestion {id: $id}) RETURN s", id=suggestion_id).single())


def update_suggestion(driver: Driver, suggestion_id: str, fields: dict[str, Any]) -> dict | None:
    """Set status, text and/or detail; returns the updated node, or None if it does not exist."""
    allowed = {k: v for k, v in fields.items() if k in ("status", "text", "detail")}
    with driver.session() as session:
        record = session.run(
            "MATCH (s:Suggestion {id: $id}) SET s += $fields, s.updated_at = $now RETURN s",
            id=suggestion_id,
            fields=allowed,
            now=_now(),
        ).single()
        return _row(record)


def toggle_vote(driver: Driver, suggestion_id: str, user: str) -> dict | None:
    """Add the user's vote, or remove it when it is already there."""
    with driver.session() as session:
        record = session.run(
            """
            MATCH (s:Suggestion {id: $id})
            SET s.voters = CASE WHEN $user IN coalesce(s.voters, [])
                                THEN [v IN s.voters WHERE v <> $user]
                                ELSE coalesce(s.voters, []) + [$user] END
            RETURN s
            """,
            id=suggestion_id,
            user=user,
        ).single()
        return _row(record)


def add_seen(driver: Driver, suggestion_id: str, user: str | None) -> dict | None:
    """The chat proposed this again: ``seen`` + 1 and the user's vote (never removed)."""
    with driver.session() as session:
        record = session.run(
            """
            MATCH (s:Suggestion {id: $id})
            SET s.seen = coalesce(s.seen, 1) + 1,
                s.voters = CASE WHEN $user IS NULL OR $user IN coalesce(s.voters, [])
                                THEN coalesce(s.voters, []) ELSE coalesce(s.voters, []) + [$user] END
            RETURN s
            """,
            id=suggestion_id,
            user=user,
        ).single()
        return _row(record)


def delete_suggestion(driver: Driver, suggestion_id: str) -> bool:
    with driver.session() as session:
        record = session.run(
            "MATCH (s:Suggestion {id: $id}) WITH s, s.id AS id DETACH DELETE s RETURN count(id) AS n",
            id=suggestion_id,
        ).single()
        return bool(record and record["n"])


def find_similar(driver: Driver, statuses: tuple[str, ...] = ("open", "planned")) -> list[dict]:
    """Candidate rows (``id``, ``text``, ``status``) a new suggestion is compared with."""
    with driver.session() as session:
        result = session.run(
            "MATCH (s:Suggestion) WHERE s.status IN $statuses RETURN s", statuses=list(statuses)
        )
        return [dict(r["s"]) for r in result]
