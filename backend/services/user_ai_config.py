"""Resolve effective AI credential settings for current user."""
from __future__ import annotations

from typing import Optional

from config import settings
from db.connection import get_driver
from db.queries.users import get_user_ai_keys
from services.auth import get_request_user


NIKLAS_USER = "niklas"


def _is_niklas(username: Optional[str]) -> bool:
    return bool(username and username.strip().lower() == NIKLAS_USER)


def _normalize(value: Optional[str]) -> str:
    return (value or "").strip()


def get_effective_ai_config(username: Optional[str] = None) -> dict:
    """
    Return effective AI config for a user.

    Rules:
    - For user 'niklas': fall back to env keys when user-specific keys are not set.
    - For all other users: only use user-specific keys from DB.
    - Outside authenticated request (username is None): use env keys.
    """
    name = username if username is not None else get_request_user()

    env_personal = _normalize(settings.anthropic_api_key)
    env_work = _normalize(settings.anthropic_work_api_key)
    env_work_base = _normalize(settings.anthropic_work_base_url)

    if not name:
        return {
            "anthropic_api_key": env_personal,
            "anthropic_work_api_key": env_work,
            "anthropic_work_base_url": env_work_base,
            "source_personal": "env" if env_personal else "none",
            "source_work": "env" if env_work else "none",
        }

    user_cfg = get_user_ai_keys(get_driver(), name)
    user_personal = _normalize(user_cfg.get("anthropic_api_key") if user_cfg else "")
    user_work = _normalize(user_cfg.get("anthropic_work_api_key") if user_cfg else "")
    user_work_base = _normalize(user_cfg.get("anthropic_work_base_url") if user_cfg else "")

    if _is_niklas(name):
        personal = user_personal or env_personal
        work = user_work or env_work
        work_base = user_work_base or env_work_base
        return {
            "anthropic_api_key": personal,
            "anthropic_work_api_key": work,
            "anthropic_work_base_url": work_base,
            "source_personal": "user" if user_personal else ("env" if env_personal else "none"),
            "source_work": "user" if user_work else ("env" if env_work else "none"),
        }

    return {
        "anthropic_api_key": user_personal,
        "anthropic_work_api_key": user_work,
        "anthropic_work_base_url": user_work_base,
        "source_personal": "user" if user_personal else "none",
        "source_work": "user" if user_work else "none",
    }


def get_masked_ai_config(username: str) -> dict:
    """Return masked status for settings UI without exposing raw keys."""
    effective = get_effective_ai_config(username)
    user_cfg = get_user_ai_keys(get_driver(), username)
    user_personal = _normalize(user_cfg.get("anthropic_api_key") if user_cfg else "")
    user_work = _normalize(user_cfg.get("anthropic_work_api_key") if user_cfg else "")
    user_work_base = _normalize(user_cfg.get("anthropic_work_base_url") if user_cfg else "")

    return {
        "username": username,
        "uses_env_fallback": _is_niklas(username),
        "has_user_anthropic_api_key": bool(user_personal),
        "has_user_anthropic_work_api_key": bool(user_work),
        "user_anthropic_work_base_url": user_work_base,
        "effective_has_anthropic_api_key": bool(_normalize(effective["anthropic_api_key"])),
        "effective_has_anthropic_work_api_key": bool(_normalize(effective["anthropic_work_api_key"])),
        "effective_anthropic_work_base_url": _normalize(effective["anthropic_work_base_url"]),
        "source_personal": effective["source_personal"],
        "source_work": effective["source_work"],
    }
