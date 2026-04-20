"""Figure extraction, listing, and vision-chat endpoints."""
from __future__ import annotations

import base64
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from db.connection import get_driver
from db.queries.figures import create_figure, list_figures, get_figure, delete_figures_for_paper
from db.queries.papers import get_paper
from models.schemas import FigureOut, FigureChatRequest, FigureExtractRequest
from services.drive import upload_image, get_file_url, download_pdf, delete_file
from services.figure_extractor import extract_figures

log = logging.getLogger(__name__)
router = APIRouter(prefix="/papers", tags=["figures"])


def _enrich_figure(fig: dict) -> dict:
    """Add drive_url to a figure dict."""
    fig = dict(fig)
    if fig.get("drive_file_id"):
        fig["drive_url"] = get_file_url(fig["drive_file_id"])
    else:
        fig["drive_url"] = None
    return fig


@router.get("/{paper_id}/figures", response_model=list[FigureOut])
def list_paper_figures(paper_id: str):
    driver = get_driver()
    figs = list_figures(driver, paper_id)
    return [_enrich_figure(f) for f in figs]


@router.get("/{paper_id}/figures/{figure_id}/image")
def get_figure_image(paper_id: str, figure_id: str):
    """Proxy the figure image from Google Drive so the browser can render it."""
    driver = get_driver()
    fig = get_figure(driver, figure_id)
    if not fig or fig.get("paper_id") != paper_id:
        raise HTTPException(status_code=404, detail="Figure not found")
    if not fig.get("drive_file_id"):
        raise HTTPException(status_code=404, detail="No image stored for this figure")
    try:
        image_bytes = download_pdf(fig["drive_file_id"])  # download_pdf works for any file
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Drive download failed: {exc}")
    return Response(content=image_bytes, media_type="image/png", headers={"Content-Disposition": "inline"})


@router.post("/{paper_id}/figures/extract")
def extract_paper_figures(paper_id: str, body: FigureExtractRequest):
    """
    Download the paper PDF from Drive, extract figures, save to Drive + Neo4j.
    Deletes any previously extracted figures first.
    """
    driver = get_driver()
    paper = get_paper(driver, paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    if not paper.get("drive_file_id"):
        raise HTTPException(status_code=422, detail="Paper has no PDF on Drive")

    try:
        pdf_bytes = download_pdf(paper["drive_file_id"])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not download PDF: {e}")

    # Delete old figure files from Drive, then clear Neo4j nodes
    old_figs = list_figures(driver, paper_id)
    for old_fig in old_figs:
        if old_fig.get("drive_file_id"):
            try:
                delete_file(old_fig["drive_file_id"])
            except Exception as exc:
                log.warning("Could not delete old figure from Drive: %s", exc)
    delete_figures_for_paper(driver, paper_id)

    try:
        figures = extract_figures(pdf_bytes, caption_method=body.caption_method)
    except Exception as e:
        log.error("Figure extraction failed for %s: %s", paper_id, e)
        raise HTTPException(status_code=500, detail=f"Extraction failed: {e}")

    saved = 0
    for i, fig in enumerate(figures):
        try:
            filename = f"{paper_id}_p{fig['page_number']}_{i+1}.png"
            drive_file_id = upload_image(fig["image_bytes"], filename)
            create_figure(driver, {
                "paper_id": paper_id,
                "figure_number": fig["figure_number"],
                "caption": fig["caption"],
                "drive_file_id": drive_file_id,
                "page_number": fig["page_number"],
            })
            saved += 1
        except Exception as e:
            log.warning("Could not save figure %d for paper %s: %s", i, paper_id, e)

    return {"extracted": saved}


@router.post("/{paper_id}/figures/{figure_id}/chat")
def chat_with_figure(paper_id: str, figure_id: str, body: FigureChatRequest):
    """Ask Claude a question about a specific figure image (vision)."""
    from config import settings
    import anthropic
    import httpx

    driver = get_driver()
    fig = get_figure(driver, figure_id)
    if not fig or fig.get("paper_id") != paper_id:
        raise HTTPException(status_code=404, detail="Figure not found")

    try:
        image_bytes = download_pdf(fig["drive_file_id"])  # works for any file
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not load figure image: {e}")

    b64 = base64.standard_b64encode(image_bytes).decode()

    system = (
        "You are a research assistant analysing a figure from an academic paper. "
        "Answer concisely based on what you can see in the image."
    )
    context = ""
    if fig.get("caption"):
        context = f"\n\nFigure caption: {fig['caption']}"

    messages = [{
        "role": "user",
        "content": [
            {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": b64},
            },
            {"type": "text", "text": body.question + context},
        ],
    }]

    try:
        if body.model == "claude-work":
            if not settings.anthropic_work_api_key:
                raise ValueError("Work API key not configured.")
            def _ssl_verify():
                if not settings.ssl_verify:
                    return False
                return settings.ssl_ca_bundle or True
            client = anthropic.Anthropic(
                api_key=settings.anthropic_work_api_key,
                base_url=settings.anthropic_work_base_url or None,
                http_client=httpx.Client(verify=_ssl_verify()),
            )
        else:
            client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=1024,
            system=system,
            messages=messages,
        )
        return {"answer": response.content[0].text}
    except Exception as e:
        log.error("Figure chat failed: %s", e)
        raise HTTPException(status_code=502, detail=str(e))
