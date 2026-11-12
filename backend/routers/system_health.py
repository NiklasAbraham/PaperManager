"""System health endpoint (.specs/016_health.md): admin only."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from db.connection import get_driver
from db.queries import users as users_q
from services import system_health
from services.auth import get_current_user

log = logging.getLogger(__name__)
router = APIRouter(prefix="/system", tags=["system"], dependencies=[Depends(get_current_user)])


def _is_admin(username: str) -> bool:
    """Admin check; any failure counts as "not an admin"."""
    try:
        return bool(users_q.is_user_admin(get_driver(), username))
    except Exception:  # noqa: BLE001
        log.exception("Admin check failed for %s", username)
        return False


@router.get("/health")
def get_health(refresh: bool = False, user: str = Depends(get_current_user)):
    """State of the whole instance; checks are cached, ``refresh=true`` recomputes them all."""
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="Only an admin can see the system health")
    return system_health.collect(refresh=refresh)
