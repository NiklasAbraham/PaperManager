"""Start/stop docling-serve on hermione via the Inference Manager (sync API)."""
from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from typing import Generator

import httpx

from config import settings

log = logging.getLogger(__name__)

POLL_INTERVAL = 5


def _inference_manager_url() -> str:
    return (settings.inference_manager_url or os.getenv("INFERENCE_MANAGER_URL", "")).rstrip("/")


def _docling_base_url() -> str:
    host = (settings.docling_remote_host or os.getenv("HERMIONE_HOST", "129.69.129.133")).strip()
    port = settings.docling_host_port
    return f"http://{host}:{port}"


@contextmanager
def on_demand_docling(
    ready_timeout: int | None = None,
) -> Generator[str, None, None]:
    """
    Context manager: spin up docling-serve on GPU 2, yield base URL, tear down on exit.

    Yields:
        Base URL of docling-serve, e.g. http://129.69.129.133:8004
    """
    manager_url = _inference_manager_url()
    if not manager_url:
        raise ValueError("INFERENCE_MANAGER_URL is required for on-demand Docling.")

    timeout = ready_timeout or settings.docling_ready_timeout
    job_id: str | None = None

    with httpx.Client(timeout=60) as client:
        resp = client.post(f"{manager_url}/docling")
        if resp.status_code == 409:
            # GPU occupied by an orphaned docling-serve (e.g. left over from a
            # crashed run that never tore down). Force-free the GPU and retry once.
            log.warning(
                "On-demand Docling start got 409 (%s); forcing GPU free and retrying once.",
                resp.text.strip(),
            )
            try:
                client.delete(f"{manager_url}/models/current/force")
            except Exception as exc:
                log.warning("Force-free GPU failed before Docling retry | %s", exc)
            resp = client.post(f"{manager_url}/docling")
        resp.raise_for_status()
        job_id = resp.json()["job_id"]
        log.info("On-demand Docling started | job_id=%s", job_id)

        start = time.monotonic()
        while True:
            if time.monotonic() - start > timeout:
                raise TimeoutError(f"docling-serve not ready within {timeout}s")

            status_resp = client.get(f"{manager_url}/docling/{job_id}")
            status_resp.raise_for_status()
            data = status_resp.json()

            if data["status"] == "ready":
                break
            if data["status"] == "error":
                raise RuntimeError(data.get("error_message") or "docling-serve failed to start")
            time.sleep(POLL_INTERVAL)

        manager_root = _inference_manager_url()
        try:
            yield manager_root
        finally:
            try:
                client.delete(f"{manager_url}/docling/{job_id}")
                log.info("On-demand Docling stopped | job_id=%s", job_id)
            except Exception as exc:
                log.warning("Failed to stop on-demand Docling | job_id=%s | %s", job_id, exc)
