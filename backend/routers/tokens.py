"""Token ledger API (.specs/013_tokens.md): what the LLM calls cost, from services/usage.

An admin sees every user and may filter with ``user=``; anyone else sees only their own rows.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query

from services.auth import get_current_user
from services.usage import ledger, pricing

log = logging.getLogger(__name__)

router = APIRouter(prefix="/tokens", tags=["tokens"], dependencies=[Depends(get_current_user)])


def _is_admin(username: str) -> bool:
    """True when the user is an admin (False when that cannot be checked)."""
    try:
        from db.connection import get_driver
        from db.queries.users import is_user_admin

        return bool(is_user_admin(get_driver(), username))
    except Exception as exc:  # noqa: BLE001
        log.debug("admin check failed for %s: %s", username, exc)
        return False


def _paper_titles(ids: list[str]) -> dict[str, Optional[str]]:
    """Titles of the papers in the library; missing papers (and a failed read) give no entry."""
    if not ids:
        return {}
    try:
        from db.connection import get_driver

        with get_driver().session() as session:
            rows = session.run(
                "MATCH (p:Paper) WHERE p.id IN $ids RETURN p.id AS id, p.title AS title", ids=ids
            ).data()
        return {r["id"]: r.get("title") for r in rows}
    except Exception as exc:  # noqa: BLE001
        log.debug("paper titles unavailable: %s", exc)
        return {}


def _scope(current_user: str, user: str | None) -> tuple[bool, Optional[str]]:
    """``(is_admin, user filter)``: non-admins are always held to their own rows."""
    admin = _is_admin(current_user)
    if not admin:
        return False, current_user
    return True, (user or "").strip() or None


@router.get("/summary")
def tokens_summary(
    days: int = Query(30, ge=1, le=366),
    user: Optional[str] = None,
    feature: Optional[str] = None,
    model: Optional[str] = None,
    current_user: str = Depends(get_current_user),
) -> dict[str, Any]:
    """Totals, per-day/week/feature/model/provider/user breakdowns and the costliest calls."""
    admin, scope_user = _scope(current_user, user)
    data = ledger.summary(
        days=days, user=scope_user, feature=feature or None, model=model or None, include_users=admin,
    )
    titles = _paper_titles([p["paper_id"] for p in data["top_papers"]])
    for paper in data["top_papers"]:
        paper["title"] = titles.get(paper["paper_id"])
    data["scope"] = {"user": scope_user, "is_admin": admin}
    data["prices_as_of"] = pricing.PRICES_AS_OF
    return data


@router.get("/calls")
def tokens_calls(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: Optional[str] = None,
    feature: Optional[str] = None,
    model: Optional[str] = None,
    provider: Optional[str] = None,
    paper_id: Optional[str] = None,
    ok: Optional[bool] = None,
    days: Optional[int] = Query(None, ge=1, le=3660),
    current_user: str = Depends(get_current_user),
) -> dict[str, Any]:
    """Newest-first page of recorded calls."""
    _, scope_user = _scope(current_user, user)
    rows, total = ledger.calls(
        limit=limit, offset=offset, days=days, user=scope_user, feature=feature or None,
        model=model or None, provider=provider or None, paper_id=paper_id or None, ok=ok,
    )
    return {"calls": rows, "total": total}


@router.get("/prices")
def tokens_prices() -> dict[str, Any]:
    """The list-price table the costs are computed from (USD per million tokens)."""
    from config import settings

    models = [
        {"prefix": prefix, "input": row[0], "output": row[1], "cache_write": row[2], "cache_read": row[3]}
        for prefix, row in sorted(pricing.price_table().items())
    ]
    return {"as_of": pricing.PRICES_AS_OF, "litellm_free": bool(settings.usage_litellm_free), "models": models}
