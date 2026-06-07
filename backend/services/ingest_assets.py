"""Persist extracted figures and tables to Drive + Neo4j."""
from __future__ import annotations

import logging

from db.connection import Driver
from db.queries.figures import create_figure
from db.queries.tables import create_table
from services.drive import upload_image

log = logging.getLogger(__name__)


def save_figures_and_tables(
    driver: Driver,
    paper_id: str,
    extraction: dict,
) -> tuple[int, int]:
    """Save figures (Drive + Neo4j) and tables (Neo4j). Returns (figures_saved, tables_saved)."""
    figures = extraction.get("figures") or []
    tables = extraction.get("tables") or []

    saved_figures = 0
    for i, fig in enumerate(figures):
        try:
            fig_filename = f"{paper_id}_p{fig['page_number']}_{i+1}.png"
            fig_drive_id = upload_image(fig["image_bytes"], fig_filename)
            create_figure(driver, {
                "paper_id": paper_id,
                "figure_number": fig.get("figure_number"),
                "caption": fig.get("caption"),
                "drive_file_id": fig_drive_id,
                "page_number": fig.get("page_number"),
            })
            saved_figures += 1
        except Exception as exc:
            log.warning("Could not save figure %d for paper %s: %s", i, paper_id, exc)

    saved_tables = 0
    for tbl in tables:
        try:
            create_table(driver, {
                "paper_id": paper_id,
                "table_number": tbl.get("table_number"),
                "caption": tbl.get("caption"),
                "markdown_content": tbl.get("markdown_content"),
                "page_number": tbl.get("page_number"),
            })
            saved_tables += 1
        except Exception as exc:
            log.warning("Could not save table for paper %s: %s", paper_id, exc)

    return saved_figures, saved_tables
