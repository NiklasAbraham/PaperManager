"""Call a remote docling-serve instance (local or on-demand on hermione)."""
from __future__ import annotations

import io
import json
import logging
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import httpx

from config import settings

log = logging.getLogger(__name__)

# docling-serve /v1/convert/file expects flat multipart fields (not a nested "options" JSON).
_DEFAULT_CONVERT_OPTIONS: dict[str, Any] = {
    "from_formats": ["pdf"],
    "to_formats": ["md", "json"],
    "include_images": True,
    "images_scale": float(settings.docling_images_scale),
    # referenced + zip: picture crops are generated and shipped in artifacts/ (see #576).
    "image_export_mode": "referenced",
    "do_ocr": True,
    "do_table_structure": True,
    "pdf_backend": "dlparse_v2",
}


def _encode_multipart_options(opts: dict[str, Any]) -> list[tuple[str, str]]:
    """Flatten convert options into multipart form fields for docling-serve."""
    parts: list[tuple[str, str]] = []
    for key, value in opts.items():
        if value is None:
            continue
        if isinstance(value, bool):
            parts.append((key, "true" if value else "false"))
        elif isinstance(value, (list, tuple)):
            for item in value:
                parts.append((key, str(item)))
        elif isinstance(value, dict):
            parts.append((key, json.dumps(value)))
        else:
            parts.append((key, str(value)))
    return parts


def _build_multipart(
    pdf_bytes: bytes,
    filename: str,
    opts: dict[str, Any],
) -> list[tuple[str, tuple]]:
    multipart: list[tuple[str, tuple]] = [
        ("files", (filename, pdf_bytes, "application/pdf")),
    ]
    for key, value in _encode_multipart_options(opts):
        multipart.append((key, (None, value)))
    return multipart


def _document_block(payload: dict[str, Any]) -> dict[str, Any]:
    document = payload.get("document")
    if isinstance(document, dict):
        return document
    return payload


def _json_content_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return bool(value)
    return True


def _extract_json_content(payload: dict[str, Any]) -> Any | None:
    doc = _document_block(payload)
    for block in (doc, payload):
        if not isinstance(block, dict):
            continue
        for key in ("json_content", "json"):
            value = block.get(key)
            if _json_content_present(value):
                return value
    return None


def _validate_convert_status(payload: dict[str, Any]) -> None:
    status = payload.get("status")
    if status not in ("failure", "skipped"):
        return
    errors = payload.get("errors") or []
    detail = "; ".join(str(err) for err in errors) if errors else str(status)
    raise RuntimeError(f"docling-serve conversion {status}: {detail}")


def _resolve_asset_path(root: Path, uri: str) -> Path | None:
    """Locate a picture file from a docling-serve zip extract."""
    name = Path(uri).name
    candidates = (
        root / uri,
        root / name,
        root / "artifacts" / name,
        root / "artifacts" / uri,
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    for path in root.rglob(name):
        if path.is_file():
            return path
    return None


def _embed_pictures_in_doc_dict(doc_dict: dict[str, Any], assets_root: Path) -> int:
    """Replace file URIs with data-URI ImageRefs so get_image() works off-box."""
    from docling_core.types.doc import ImageRef
    from PIL import Image

    embedded = 0
    for pic in doc_dict.get("pictures") or []:
        if not isinstance(pic, dict):
            continue
        img = pic.get("image")
        if not isinstance(img, dict):
            continue
        uri = img.get("uri")
        if not uri or str(uri).startswith("data:"):
            continue
        asset_path = _resolve_asset_path(assets_root, str(uri))
        if asset_path is None:
            log.debug("Picture asset not found in zip | uri=%s", uri)
            continue
        pil = Image.open(asset_path)
        dpi = int(img.get("dpi") or 144)
        pic["image"] = ImageRef.from_pil(pil, dpi=dpi).model_dump(mode="json")
        embedded += 1
    return embedded


def _embed_assets_in_payload(payload: dict[str, Any], assets_root: Path) -> int:
    json_content = _extract_json_content(payload)
    if isinstance(json_content, dict):
        return _embed_pictures_in_doc_dict(json_content, assets_root)
    return 0


def _embed_pictures_via_manager(payload: dict[str, Any], manager_url: str) -> int:
    """Fetch referenced picture PNGs from the inference manager and embed as data URIs."""
    json_content = _extract_json_content(payload)
    if not isinstance(json_content, dict):
        return 0

    from docling_core.types.doc import ImageRef
    from PIL import Image

    embedded = 0
    base = manager_url.rstrip("/")
    with httpx.Client(timeout=120.0) as client:
        for pic in json_content.get("pictures") or []:
            if not isinstance(pic, dict):
                continue
            img = pic.get("image")
            if not isinstance(img, dict):
                continue
            uri = img.get("uri")
            if not uri or str(uri).startswith("data:"):
                continue
            name = Path(str(uri)).name
            try:
                resp = client.get(f"{base}/docling/assets/{name}")
                resp.raise_for_status()
            except Exception as exc:
                log.warning("Could not fetch docling asset %s: %s", name, exc)
                continue
            pil = Image.open(io.BytesIO(resp.content))
            dpi = int(img.get("dpi") or 144)
            pic["image"] = ImageRef.from_pil(pil, dpi=dpi).model_dump(mode="json")
            embedded += 1

    if embedded:
        log.info("Embedded %d picture(s) via inference manager assets", embedded)
    return embedded


def _payload_from_zip(zip_bytes: bytes) -> dict[str, Any]:
    """Parse docling-serve zip export into an in-body-style JSON payload."""
    with tempfile.TemporaryDirectory(prefix="docling_zip_") as tmp:
        root = Path(tmp)
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            zf.extractall(root)

        json_paths = sorted(root.rglob("*.json"), key=lambda p: p.stat().st_size, reverse=True)
        if not json_paths:
            raise ValueError("docling-serve zip contains no JSON files")

        for path in json_paths:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                continue

            if _extract_json_content(data):
                n = _embed_assets_in_payload(data, root)
                log.info("Loaded docling zip | json=%s | pictures_embedded=%d", path.name, n)
                return data

            if data.get("schema_name") == "DoclingDocument":
                n = _embed_pictures_in_doc_dict(data, root)
                log.info(
                    "Loaded docling zip | document=%s | pictures_embedded=%d",
                    path.name,
                    n,
                )
                return {
                    "status": "success",
                    "document": {"json_content": data},
                }

        raise ValueError(
            "docling-serve zip has JSON files but none contain DoclingDocument content"
        )


def _is_zip_response(resp: httpx.Response) -> bool:
    ctype = (resp.headers.get("content-type") or "").lower()
    if "zip" in ctype or "octet-stream" in ctype:
        return True
    return len(resp.content) >= 2 and resp.content[:2] == b"PK"


def convert_pdf(
    pdf_bytes: bytes,
    base_url: str,
    filename: str = "document.pdf",
    options: dict[str, Any] | None = None,
    timeout: float = 600.0,
    via_manager_proxy: bool = False,
    zip_with_assets: bool = True,
) -> dict[str, Any]:
    """Convert a PDF via docling-serve and return the JSON body.

    When *via_manager_proxy* is True, *base_url* is the inference manager root and
    requests go to ``/docling/convert/file`` (for clients outside the VPN).

    With *zip_with_assets* (default), uses ``target=zip`` so picture PNGs are
    downloaded and embedded into ``json_content`` for client-side ``get_image()``.
    """
    if via_manager_proxy:
        url = f"{base_url.rstrip('/')}/docling/convert/file"
    else:
        url = f"{base_url.rstrip('/')}/v1/convert/file"
    opts = {**_DEFAULT_CONVERT_OPTIONS, **(options or {})}
    if zip_with_assets:
        opts = {**opts, "target": "zip"}

    multipart = _build_multipart(pdf_bytes, filename, opts)

    with httpx.Client(timeout=timeout) as client:
        resp = client.post(url, files=multipart)
        resp.raise_for_status()
        if zip_with_assets and _is_zip_response(resp):
            payload = _payload_from_zip(resp.content)
        else:
            payload = resp.json()

    _validate_convert_status(payload)
    if via_manager_proxy and _extract_json_content(payload):
        _embed_pictures_via_manager(payload, base_url)
    if _extract_json_content(payload) is None:
        doc = _document_block(payload)
        log.warning(
            "docling-serve response missing json_content | status=%s document_keys=%s top_keys=%s",
            payload.get("status"),
            list(doc.keys()) if isinstance(doc, dict) else type(doc).__name__,
            list(payload.keys()),
        )
    return payload


def load_document_from_response(payload: dict[str, Any]):
    """Deserialize a DoclingDocument from a docling-serve convert response."""
    _validate_convert_status(payload)
    json_content = _extract_json_content(payload)
    if json_content is None:
        doc = _document_block(payload)
        log.error(
            "docling-serve response has no document.json_content | status=%s document_keys=%s top_keys=%s",
            payload.get("status"),
            list(doc.keys()) if isinstance(doc, dict) else type(doc).__name__,
            list(payload.keys()),
        )
        raise ValueError("docling-serve response has no document.json_content")

    try:
        from docling.datamodel.document import DoclingDocument
    except ImportError:
        from docling_core.types.doc import DoclingDocument

    if isinstance(json_content, str):
        return DoclingDocument.model_validate_json(json_content)
    return DoclingDocument.model_validate(json_content)
