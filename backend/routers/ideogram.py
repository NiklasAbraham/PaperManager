"""Ideogram text-to-image proxy.

The frontend never talks to the inference manager directly — these authed
endpoints forward to it so the session cookie, CORS, and origin checks all still
apply. The inference manager owns the single-tenant GPU-2 lifecycle (spin-up,
idle-timeout reaping); this router is a thin, stateless-ish pass-through.

A module-level cache of the current ideogram ``job_id`` lets a browser reload
re-attach to a running session instead of failing to start a second one on the
already-busy GPU. It is best-effort (assumes a single backend process, which is
how PaperManager runs) — correctness never depends on it, since the manager is
the source of truth.
"""
from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from config import settings
from services.auth import get_current_user

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/ideogram",
    tags=["ideogram"],
    dependencies=[Depends(get_current_user)],
)

# Best-effort cache of the active ideogram job so a page reload can re-attach.
_current_job_id: str | None = None

_GENERATE_TIMEOUT = httpx.Timeout(600.0, connect=30.0)
_CONTROL_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


class GenerateBody(BaseModel):
    prompt: str | None = None
    caption_json: dict | str | None = None
    width: int = 1024
    height: int = 1024
    seed: int = 0
    sampler_preset: str = "V4_QUALITY_48"
    magic_prompt: bool = False
    raise_on_caption_issues: bool = False


class MagicPromptBody(BaseModel):
    prompt: str
    width: int = 1024
    height: int = 1024
    model: str = "gemma"  # "gemma" (LiteLLM) | "claude" (Anthropic)


def _manager_base() -> str:
    base = (settings.inference_manager_url or "").rstrip("/")
    if not base:
        raise HTTPException(status_code=503, detail="inference manager is not configured")
    return base


def _unwrap_proxy(payload: dict) -> dict:
    """The manager wraps upstream failures in a ``_proxy_error`` envelope."""
    if isinstance(payload, dict) and payload.get("_proxy_error"):
        raise HTTPException(
            status_code=int(payload.get("upstream_status", 502)),
            detail=payload.get("detail", "ideogram upstream error"),
        )
    return payload


@router.post("/session/start")
async def start_session():
    """Ensure the Ideogram model is spinning up on GPU 2; returns job status."""
    global _current_job_id
    base = _manager_base()
    async with httpx.AsyncClient(timeout=_CONTROL_TIMEOUT) as client:
        # Re-attach to an existing session if we still know its id.
        if _current_job_id:
            try:
                r = await client.get(f"{base}/ideogram/{_current_job_id}")
                if r.status_code == 200:
                    return r.json()
            except httpx.RequestError:
                pass
            _current_job_id = None

        try:
            r = await client.post(f"{base}/ideogram")
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=f"cannot reach inference manager: {exc}")

    if r.status_code == 409:
        # GPU busy with something else (docling / vLLM) — surface as conflict.
        raise HTTPException(status_code=409, detail=r.json().get("detail", "GPU busy"))
    if r.status_code >= 400:
        raise HTTPException(status_code=r.status_code, detail=r.text[:500])

    data = r.json()
    _current_job_id = data.get("job_id")
    return data


@router.get("/session/status")
async def session_status():
    """Return current session status; keeps the model warm (touches last_used)."""
    global _current_job_id
    base = _manager_base()
    if not _current_job_id:
        return {"status": "stopped", "job_id": None}
    async with httpx.AsyncClient(timeout=_CONTROL_TIMEOUT) as client:
        try:
            r = await client.get(f"{base}/ideogram/{_current_job_id}")
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=f"cannot reach inference manager: {exc}")
    if r.status_code == 404:
        _current_job_id = None
        return {"status": "stopped", "job_id": None}
    if r.status_code >= 400:
        raise HTTPException(status_code=r.status_code, detail=r.text[:500])
    return r.json()


@router.post("/session/stop")
async def stop_session():
    """Tear the model down now (also happens automatically on idle-timeout)."""
    global _current_job_id
    base = _manager_base()
    job_id = _current_job_id
    _current_job_id = None
    if not job_id:
        return {"stopped": False}
    async with httpx.AsyncClient(timeout=_CONTROL_TIMEOUT) as client:
        try:
            await client.delete(f"{base}/ideogram/{job_id}")
        except httpx.RequestError as exc:
            log.warning("ideogram stop: cannot reach inference manager: %s", exc)
    return {"stopped": True}


@router.post("/generate")
async def generate(body: GenerateBody):
    """Generate an image (or regenerate a single edited box with a locked seed)."""
    base = _manager_base()
    async with httpx.AsyncClient(timeout=_GENERATE_TIMEOUT) as client:
        try:
            r = await client.post(f"{base}/ideogram/generate", json=body.model_dump())
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=f"cannot reach inference manager: {exc}")
    if r.status_code >= 400:
        raise HTTPException(status_code=r.status_code, detail=r.text[:1000])
    return _unwrap_proxy(r.json())


@router.post("/magic-prompt")
async def magic_prompt(body: MagicPromptBody):
    """Expand a plain prompt into the structured 'boxes' caption via LiteLLM/Gemma.

    Runs on the always-on Gemma model (GPUs 0/1), so it never contends with
    Ideogram on GPU 2 and needs no external key.
    """
    from services.ideogram_magic import expand_prompt_to_caption

    try:
        caption = await run_in_threadpool(
            expand_prompt_to_caption, body.prompt, body.width, body.height, body.model
        )
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — surface LiteLLM/config errors cleanly
        raise HTTPException(status_code=502, detail=f"magic-prompt failed: {exc}")
    return {"caption": caption}
