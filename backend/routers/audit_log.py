"""Audit log router — track and view multi-user actions."""
from __future__ import annotations
import logging
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from db.connection import get_driver
from db.queries.audit_log import get_audit_logs, get_user_activity_feed, get_entity_history
from services.auth import get_current_user

log = logging.getLogger(__name__)
router = APIRouter(prefix="/audit", tags=["audit"])


class AuditLogOut(BaseModel):
    id: str
    timestamp: str
    username: str
    action_type: str
    entity_type: str
    entity_id: str
    details: str | None = None


@router.get("/logs", response_model=list[AuditLogOut])
def list_audit_logs(
    limit: int = 100,
    username: str | None = None,
    entity_type: str | None = None,
    action_type: str | None = None,
    current_user: str = Depends(get_current_user),
):
    """List audit logs with optional filtering (admin only)."""
    from db.queries.users import is_user_admin
    if not is_user_admin(get_driver(), current_user):
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    
    logs = get_audit_logs(get_driver(), limit, username, entity_type, action_type)
    return [AuditLogOut(**log) for log in logs]


@router.get("/my-activity", response_model=list[AuditLogOut])
def get_my_activity(limit: int = 50, current_user: str = Depends(get_current_user)):
    """Get the current user's activity feed."""
    logs = get_user_activity_feed(get_driver(), current_user, limit)
    return [AuditLogOut(**log) for log in logs]


@router.get("/entity/{entity_id}", response_model=list[AuditLogOut])
def get_entity_audit_history(entity_id: str, limit: int = 50, current_user: str = Depends(get_current_user)):
    """Get audit history for a specific entity."""
    logs = get_entity_history(get_driver(), entity_id, limit)
    return [AuditLogOut(**log) for log in logs]
