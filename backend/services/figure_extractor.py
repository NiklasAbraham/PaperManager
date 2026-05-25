"""Extract figures from academic PDFs using Docling (primary) with pypdf fallback."""
from __future__ import annotations

import base64
import io
import json
import logging
import re
import tempfile
import os
from pathlib import Path

log = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"
_MIN_WIDTH = 80
_MIN_HEIGHT = 80
_MIN_BYTES = 5_000  # skip very small image data (icons, bullets)

# ── Docling singletons ─────────────────────────────────────────────────────────
# Full converter: generates page + picture images — great quality, high memory.
# Lite converter: no page images — tables only, much cheaper for large docs.
_MAX_PAGES_FULL = 80   # PDFs with more pages use lite converter + pypdf for figures

_converter = None
_converter_error: str | None = None
_lite_converter = None
_lite_converter_error: str | None = None


def _get_converter():
    """Full converter: page images enabled. Use for PDFs ≤ _MAX_PAGES_FULL pages."""
    global _converter, _converter_error
    if _converter is not None:
        return _converter
    if _converter_error is not None:
        raise RuntimeError(_converter_error)
    try:
        from docling.document_converter import DocumentConverter
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import PdfFormatOption

        pipeline_options = PdfPipelineOptions()
        pipeline_options.generate_page_images = True      # needed for item.get_image()
        pipeline_options.generate_picture_images = True   # crop figure regions from page images
        pipeline_options.images_scale = 2.0               # ~144 DPI — good quality, half the memory of 4.0

        _converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
            }
        )
        log.info("Docling DocumentConverter loaded (page+picture images, 2x scale)")
        return _converter
    except Exception as exc:
        _converter_error = f"Docling unavailable: {exc}"
        log.warning("Docling load failed (will use pypdf fallback): %s", exc)
        raise RuntimeError(_converter_error)


def _get_lite_converter():
    """Lite converter: no page images. Use for large PDFs (tables only, no figure images)."""
    global _lite_converter, _lite_converter_error
    if _lite_converter is not None:
        return _lite_converter
    if _lite_converter_error is not None:
        raise RuntimeError(_lite_converter_error)
    try:
        from docling.document_converter import DocumentConverter
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import PdfFormatOption

        pipeline_options = PdfPipelineOptions()
        pipeline_options.generate_page_images = False
        pipeline_options.generate_picture_images = False

        _lite_converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
            }
        )
        log.info("Docling lite DocumentConverter loaded (no page images)")
        return _lite_converter
    except Exception as exc:
        _lite_converter_error = f"Docling unavailable: {exc}"
        raise RuntimeError(_lite_converter_error)


def _count_pdf_pages(pdf_bytes: bytes) -> int:
    """Return page count without rendering any pages. Returns 0 on error."""
    try:
        from pypdf import PdfReader
        return len(PdfReader(io.BytesIO(pdf_bytes)).pages)
    except Exception:
        return 0


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _load_prompt(filename: str) -> str:
    return (_PROMPTS_DIR / filename).read_text(encoding="utf-8")


def _pil_to_png(pil_image) -> bytes | None:
    """Convert a PIL Image to PNG bytes. Returns None if too small."""
    try:
        if pil_image.width < _MIN_WIDTH or pil_image.height < _MIN_HEIGHT:
            return None
        buf = io.BytesIO()
        pil_image.convert("RGB").save(buf, format="PNG")
        data = buf.getvalue()
        if len(data) < _MIN_BYTES:
            return None
        return data
    except Exception as e:
        log.debug("PIL → PNG conversion failed: %s", e)
        return None


def _image_bytes_to_png(image_bytes: bytes) -> bytes | None:
    """Convert raw image bytes to PNG using Pillow. Returns None if too small or invalid."""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes))
        return _pil_to_png(img)
    except Exception as e:
        log.debug("Image conversion failed: %s", e)
        return None


def _parse_captions_from_text(page_text: str, page_num: int) -> list[dict]:
    """Ask Ollama to find figure captions in page text. Returns [{number, caption}]."""
    try:
        import ollama
        from config import settings

        prompt = _load_prompt("figure_captions.txt").format(
            page=page_num,
            page_text=page_text[:4000],
        )
        response = ollama.chat(
            model=settings.ollama_model,
            messages=[{"role": "user", "content": prompt}],
            format="json",
        )
        raw = json.loads(response["message"]["content"])
        return raw.get("figures") or []
    except Exception as e:
        log.warning("Ollama caption extraction failed page %d: %s", page_num, e)
        return _regex_captions(page_text)


def _regex_captions(text: str) -> list[dict]:
    """Simple regex fallback to find Figure X: ... captions."""
    pattern = re.compile(
        r"(?:Figure|Fig\.?|FIGURE)\s+(\d+)[.:]\s*(.+?)(?=(?:Figure|Fig\.?|FIGURE|Table)\s+\d+|$)",
        re.IGNORECASE | re.DOTALL,
    )
    results = []
    for m in pattern.finditer(text):
        caption_text = re.sub(r"\s+", " ", m.group(2)).strip()[:500]
        results.append({
            "number": int(m.group(1)),
            "caption": f"Figure {m.group(1)}: {caption_text}",
        })
    return results


def _parse_captions_vision(image_bytes: bytes) -> dict | None:
    """Use Claude Haiku vision to identify figure number and caption.
    Returns None if not a scientific figure."""
    try:
        import anthropic
        from services.user_ai_config import get_effective_ai_config

        b64 = base64.standard_b64encode(image_bytes).decode()
        ai_cfg = get_effective_ai_config()
        personal_key = (ai_cfg.get("anthropic_api_key") or "").strip()
        if not personal_key:
            return None
        client = anthropic.Anthropic(api_key=personal_key)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            system="You are analysing images from an academic paper PDF.",
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/png", "data": b64},
                    },
                    {
                        "type": "text",
                        "text": (
                            "Is this a scientific figure (chart, graph, diagram, illustration)? "
                            "If NOT (e.g. logo, header, bullet, decorative), reply with just: NOT_FIGURE\n"
                            "If YES, reply with the figure number and caption in this format:\n"
                            "NUMBER: <integer or null>\nCAPTION: <full caption text or your description if no caption visible>"
                        ),
                    },
                ],
            }],
        )
        text = response.content[0].text.strip()
        if text.upper().startswith("NOT_FIGURE"):
            return None
        number = None
        caption = None
        for line in text.splitlines():
            if line.startswith("NUMBER:"):
                val = line.split(":", 1)[1].strip()
                number = int(val) if val.isdigit() else None
            elif line.startswith("CAPTION:"):
                caption = line.split(":", 1)[1].strip()
        return {"number": number, "caption": caption or text}
    except Exception as e:
        log.warning("Claude vision caption failed: %s", e)
        return {"number": None, "caption": None}


# ── Docling extraction ─────────────────────────────────────────────────────────

def _extract_figures_docling(converter, pdf_bytes: bytes, caption_method: str) -> dict:
    """
    Extract figures AND tables using Docling's layout model (RT-DETRv2).
    caption_method controls how missing figure captions are supplemented:
      - "docling": use only Docling's built-in caption matching (text proximity)
      - "ollama":  supplement missing captions with Ollama
      - "claude-vision": supplement missing captions with Claude Haiku vision

    Returns:
        {
            "figures": [{page_number, figure_number, caption, image_bytes}, ...],
            "tables":  [{page_number, table_number, caption, markdown_content}, ...],
        }
    """
    from docling.datamodel.base_models import InputFormat  # noqa: F401 (ensure docling importable)
    from docling.datamodel.document import PictureItem, TableItem

    tmp_path = None
    try:
        # Docling needs a file path, not bytes
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(pdf_bytes)
            tmp_path = tmp.name

        log.info("Docling: converting PDF (%d bytes)...", len(pdf_bytes))
        result = converter.convert(tmp_path)
        doc = result.document
        log.info("Docling: conversion done, scanning for figures and tables...")

        # Count all item types for diagnostics
        all_items = list(doc.iterate_items())
        type_counts: dict[str, int] = {}
        for item, _ in all_items:
            t = type(item).__name__
            type_counts[t] = type_counts.get(t, 0) + 1
        log.info("Docling: found %d total items: %s", len(all_items), type_counts)

        figures = []
        tables = []

        for item, _level in all_items:

            # ── Figures ──────────────────────────────────────────────────────
            if isinstance(item, PictureItem):
                try:
                    pil_image = item.get_image(doc)
                except Exception as exc:
                    log.warning("Docling get_image failed: %s", exc)
                    continue

                if pil_image is None:
                    log.warning("Docling: get_image returned None — page images may not have been generated")
                    continue

                log.info("Docling: PictureItem size=%dx%d", pil_image.width, pil_image.height)
                png = _pil_to_png(pil_image)
                if png is None:
                    log.info("Docling: skipped (too small or conversion failed)")
                    continue

                try:
                    page_no = item.prov[0].page_no
                except Exception:
                    page_no = 0

                try:
                    caption = item.caption_text(doc) or None
                except Exception:
                    caption = None

                figure_number = None
                if caption:
                    m = re.search(r"(?:Figure|Fig\.?|FIGURE)\s+(\d+)", caption, re.IGNORECASE)
                    if m:
                        figure_number = int(m.group(1))

                if not caption:
                    if caption_method == "claude-vision":
                        info = _parse_captions_vision(png)
                        if info is None:
                            continue
                        figure_number = info.get("number")
                        caption = info.get("caption")
                    elif caption_method == "ollama":
                        pass

                log.info(
                    "Docling: figure found | page=%d fig=%s caption=%.60s",
                    page_no, figure_number or "?", (caption or "—"),
                )
                figures.append({
                    "page_number": page_no,
                    "figure_number": figure_number,
                    "caption": caption,
                    "image_bytes": png,
                })

            # ── Tables ───────────────────────────────────────────────────────
            elif isinstance(item, TableItem):
                try:
                    page_no = item.prov[0].page_no
                except Exception:
                    page_no = 0

                try:
                    caption = item.caption_text(doc) or None
                except Exception:
                    caption = None

                # Parse table number from caption (e.g. "Table 3: ...")
                table_number = None
                if caption:
                    m = re.search(r"(?:Table|TABLE)\s+(\d+)", caption, re.IGNORECASE)
                    if m:
                        table_number = int(m.group(1))

                # Export as GitHub-Flavored Markdown table
                try:
                    markdown_content = item.export_to_markdown(doc)
                except Exception as exc:
                    log.warning("Docling table export_to_markdown failed: %s", exc)
                    continue

                if not markdown_content or not markdown_content.strip():
                    continue

                log.info(
                    "Docling: table found | page=%d tbl=%s caption=%.60s rows=%d",
                    page_no, table_number or "?", (caption or "—"),
                    markdown_content.count("\n"),
                )
                tables.append({
                    "page_number": page_no,
                    "table_number": table_number,
                    "caption": caption,
                    "markdown_content": markdown_content,
                })

        log.info(
            "Docling: extraction complete | %d figure(s) | %d table(s) found",
            len(figures), len(tables),
        )
        return {"figures": figures, "tables": tables}

    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


# ── pypdf fallback ─────────────────────────────────────────────────────────────

def _extract_figures_pypdf(pdf_bytes: bytes, caption_method: str) -> list[dict]:
    """
    Fallback figure extraction using pypdf image streams.
    Less accurate than Docling — misses vector figures and multi-panel composites.
    """
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf_bytes))
    results: list[dict] = []

    for page_idx, page in enumerate(reader.pages):
        page_num = page_idx + 1
        raw_images = []

        try:
            for img_obj in page.images:
                if len(img_obj.data) < _MIN_BYTES:
                    continue
                png = _image_bytes_to_png(img_obj.data)
                if png is not None:
                    raw_images.append(png)
        except Exception as e:
            log.debug("pypdf image extraction failed page %d: %s", page_num, e)
            continue

        if not raw_images:
            continue

        if caption_method == "claude-vision":
            for png in raw_images:
                info = _parse_captions_vision(png)
                if info is None:
                    continue
                results.append({
                    "page_number": page_num,
                    "figure_number": info.get("number"),
                    "caption": info.get("caption"),
                    "image_bytes": png,
                })
        else:
            try:
                page_text = page.extract_text() or ""
            except Exception:
                page_text = ""

            captions = _parse_captions_from_text(page_text, page_num) if page_text.strip() else []

            for i, png in enumerate(raw_images):
                cap = captions[i] if i < len(captions) else {}
                results.append({
                    "page_number": page_num,
                    "figure_number": cap.get("number"),
                    "caption": cap.get("caption"),
                    "image_bytes": png,
                })

    log.info("pypdf extracted %d figures (method=%s)", len(results), caption_method)
    return {"figures": results, "tables": []}


# ── Public entry point ─────────────────────────────────────────────────────────

def extract_figures(
    pdf_bytes: bytes,
    caption_method: str = "docling",
) -> dict:
    """
    Extract figures AND tables from a PDF.

    Returns:
        {
            "figures": [{page_number, figure_number, caption, image_bytes (PNG)}, ...],
            "tables":  [{page_number, table_number, caption, markdown_content}, ...],
        }

    caption_method:
        "docling"      — Docling layout model (best quality); falls back to pypdf if unavailable
        "ollama"       — Docling + Ollama to supplement missing captions
        "claude-vision"— Docling + Claude Haiku vision to supplement missing captions
    """
    n_pages = _count_pdf_pages(pdf_bytes)
    log.info("extract_figures: PDF has %d pages (threshold=%d)", n_pages, _MAX_PAGES_FULL)

    if n_pages <= _MAX_PAGES_FULL:
        # Short document — use full converter (page images, high quality)
        try:
            converter = _get_converter()
            return _extract_figures_docling(converter, pdf_bytes, caption_method)
        except RuntimeError:
            log.warning("Docling unavailable, falling back to pypdf")
        except Exception as exc:
            log.warning("Docling extraction failed, falling back to pypdf: %s", exc)
        return _extract_figures_pypdf(pdf_bytes, caption_method)
    else:
        # Large document — use lite converter (no page images) for tables,
        # then pypdf for figure image streams to avoid OOM.
        log.info("extract_figures: large PDF (%d pages) — using lite converter + pypdf for figures", n_pages)
        tables: list[dict] = []
        try:
            lite = _get_lite_converter()
            result = _extract_figures_docling(lite, pdf_bytes, caption_method)
            tables = result.get("tables", [])
        except Exception as exc:
            log.warning("Docling lite extraction failed: %s", exc)

        figures = _extract_figures_pypdf(pdf_bytes, caption_method)
        return {"figures": figures, "tables": tables}
