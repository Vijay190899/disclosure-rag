"""Locate tagged facts on the printed page.

Renders the anchor-stamped filing to PDF and reads back the link annotations
Chromium writes for each anchor. Each annotation carries a page number and a
rectangle, and both come from the pagination pass that produced the pages, so
they cannot disagree with it.

The obvious alternative does not work. Reading ``getBoundingClientRect()`` in
the browser and deriving a page index from the vertical offset located 0 of 600
facts in the M0 probe, because screen layout and print layout are different
layouts and Chromium repaginates when printing. ADR-0007 has the numbers.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from disclosure_rag.labels.facts import PROBE_URI
from disclosure_rag.provenance import Span


class Confirmation(BaseModel):
    """How well the located spans agree with an independent text search."""

    model_config = {"frozen": True}

    checked: int = 0
    confirmed: int = 0
    confirmed_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    median_iou: float = Field(default=0.0, ge=0.0, le=1.0)


def render_to_pdf(source: Path, pdf_out: Path, page_format: str = "A4") -> Path:
    """Print an XHTML filing to PDF with headless Chromium.

    Imported lazily: Playwright is a label-plane dependency and the serving
    package must stay importable without it.
    """
    from playwright.sync_api import sync_playwright

    pdf_out.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as play:
        browser = play.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(source.resolve().as_uri(), wait_until="load")
            page.pdf(path=str(pdf_out), format=page_format, print_background=True)
        finally:
            browser.close()
    return pdf_out


def locate_facts(pdf_path: Path) -> dict[str, Span]:
    """Read one span per tagged fact out of the PDF link annotations.

    Returns a mapping of fact id to span. A fact whose anchor produced no
    annotation is simply absent, so callers can report coverage rather than
    receiving a silently wrong box.
    """
    import fitz  # PyMuPDF, a label-plane dependency

    located: dict[str, Span] = {}
    document = fitz.open(pdf_path)
    try:
        for page_number in range(document.page_count):
            page = document[page_number]
            width, height = page.rect.width, page.rect.height
            for link in page.get_links():
                uri = link.get("uri") or ""
                if not uri.startswith(PROBE_URI):
                    continue
                fact_id = uri.rsplit("/", 1)[-1]
                if fact_id in located:
                    continue  # a fact rendered twice keeps its first appearance
                rect = link["from"]
                located[fact_id] = Span.from_rect(
                    page_number, rect.x0, rect.y0, rect.x1, rect.y1, width, height
                )
    finally:
        document.close()
    return located


def confirm_by_text(
    pdf_path: Path, located: dict[str, Span], displayed: dict[str, str]
) -> Confirmation:
    """Independently check located spans by searching each page for the text.

    The link annotation says where a fact is; the text search says where that
    text actually is. Agreement between two mechanisms that do not share code is
    the evidence that the labels are trustworthy. Reported at build time so a
    corpus that renders badly is visible rather than silently wrong.
    """
    import fitz

    document = fitz.open(pdf_path)
    checked = confirmed = 0
    ious: list[float] = []
    try:
        for fact_id, span in located.items():
            text = displayed.get(fact_id, "")
            if not text or span.page >= document.page_count:
                continue
            checked += 1
            page = document[span.page]
            width, height = page.rect.width, page.rect.height
            found = [
                Span.from_rect(span.page, hit.x0, hit.y0, hit.x1, hit.y1, width, height)
                for hit in page.search_for(text)
            ]
            best = max((span.iou(candidate) for candidate in found), default=0.0)
            if best > 0:
                confirmed += 1
                ious.append(best)
    finally:
        document.close()

    ious.sort()
    return Confirmation(
        checked=checked,
        confirmed=confirmed,
        confirmed_rate=confirmed / checked if checked else 0.0,
        median_iou=ious[len(ious) // 2] if ious else 0.0,
    )
