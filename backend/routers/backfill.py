"""Batch backfill operations — apply AI enrichment to existing papers."""
import logging
from fastapi import APIRouter
from db.connection import get_driver
from db.queries.papers import list_papers
from db.queries.topics import link_paper_topic

log = logging.getLogger(__name__)
router = APIRouter(prefix="/backfill", tags=["backfill"])


@router.post("/topics")
def backfill_topics():
    """Run AI topic suggestion on every paper that currently has no topics."""
    from services.ai import suggest_topics

    driver = get_driver()
    papers = list_papers(driver, skip=0, limit=10_000)

    processed = skipped = errors = 0
    for paper in papers:
        # Check if paper already has topics
        with driver.session() as session:
            count = session.run(
                "MATCH (p:Paper {id: $id})-[:ABOUT]->(:Topic) RETURN count(*) AS c",
                id=paper["id"],
            ).single()["c"]
        if count > 0:
            skipped += 1
            continue

        try:
            topics = suggest_topics(
                title=paper.get("title", ""),
                abstract=paper.get("abstract", "") or "",
                summary=paper.get("summary", "") or "",
            )
            for name in topics:
                if name:
                    link_paper_topic(driver, paper["id"], name)
            processed += 1
            log.info("Backfill topics | paper=%s | topics=%s", paper["id"], topics)
        except Exception as exc:
            log.warning("Backfill topics error | paper=%s | %s", paper["id"], exc)
            errors += 1

    return {"processed": processed, "skipped": skipped, "errors": errors}


@router.post("/summary")
def backfill_summary():
    """Generate AI summaries for papers that have raw text but no summary yet."""
    from services.ai import summarize_paper
    from db.queries.papers import update_paper

    driver = get_driver()
    papers = list_papers(driver, skip=0, limit=10_000)

    processed = skipped = errors = 0
    for paper in papers:
        if paper.get("summary"):
            skipped += 1
            continue
        raw_text = paper.get("raw_text", "") or ""
        if not raw_text.strip():
            skipped += 1
            continue

        try:
            summary = summarize_paper(raw_text, paper.get("title", ""))
            update_paper(driver, paper["id"], {"summary": summary})
            processed += 1
            log.info("Backfill summary | paper=%s", paper["id"])
        except Exception as exc:
            log.warning("Backfill summary error | paper=%s | %s", paper["id"], exc)
            errors += 1

    return {"processed": processed, "skipped": skipped, "errors": errors}


@router.post("/figures")
def backfill_figures(caption_method: str = "ollama"):
    """Extract figures for papers that have a PDF on Drive but no figures yet."""
    from services.figure_extractor import extract_figures
    from services.drive import download_pdf, upload_image
    from db.queries.figures import create_figure, list_figures

    driver = get_driver()
    papers = list_papers(driver, skip=0, limit=10_000)

    processed = skipped = errors = 0
    for paper in papers:
        if not paper.get("drive_file_id"):
            skipped += 1
            continue
        existing = list_figures(driver, paper["id"])
        if existing:
            skipped += 1
            continue

        try:
            pdf_bytes = download_pdf(paper["drive_file_id"])
            figs = extract_figures(pdf_bytes, caption_method=caption_method)
            for i, fig in enumerate(figs):
                fig_filename = f"{paper['id']}_p{fig['page_number']}_{i+1}.png"
                fig_drive_id = upload_image(fig["image_bytes"], fig_filename)
                create_figure(driver, {
                    "paper_id": paper["id"],
                    "figure_number": fig["figure_number"],
                    "caption": fig["caption"],
                    "drive_file_id": fig_drive_id,
                    "page_number": fig["page_number"],
                })
            processed += 1
            log.info("Backfill figures | paper=%s | count=%d", paper["id"], len(figs))
        except Exception as exc:
            log.warning("Backfill figures error | paper=%s | %s", paper["id"], exc)
            errors += 1

    return {"processed": processed, "skipped": skipped, "errors": errors}
