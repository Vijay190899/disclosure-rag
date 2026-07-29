"""Read a PDF into layout blocks that carry their position.

PyMuPDF returns blocks, lines and spans each with a rectangle. Block level is
the right granularity here: it is roughly a paragraph or a table row, which is
small enough to cite usefully and large enough to stay readable.

ADR-0002 records why PyMuPDF rather than LlamaParse or ColPali. The short
version is that geometry comes out of the parser natively, and the same library
renders a page with a region drawn on it, so the citation viewer shares a code
path with the parser instead of reimplementing it.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from disclosure_rag.provenance import Span


class Block(BaseModel):
    """A run of text on one page, with the region it occupies."""

    model_config = {"frozen": True}

    text: str
    span: Span
    order: int = Field(ge=0, description="Reading order within the document")


def extract_blocks(pdf_path: Path) -> list[Block]:
    """Extract every non-empty text block from a PDF, in reading order.

    Reading order is PyMuPDF's, which is heuristic and will occasionally be
    wrong on multi-column pages. That is a known limitation rather than a
    surprise: ADR-0002 accepts it, and the M2 failure taxonomy counts it.
    """
    import fitz  # PyMuPDF, an ingest dependency

    blocks: list[Block] = []
    document = fitz.open(pdf_path)
    try:
        order = 0
        for page_number in range(document.page_count):
            page = document[page_number]
            width, height = page.rect.width, page.rect.height
            for raw in page.get_text("blocks"):
                x0, y0, x1, y1, text = raw[0], raw[1], raw[2], raw[3], raw[4]
                if not text.strip():
                    continue
                blocks.append(
                    Block(
                        text=text.strip(),
                        span=Span.from_rect(page_number, x0, y0, x1, y1, width, height),
                        order=order,
                    )
                )
                order += 1
    finally:
        document.close()
    return blocks


def page_count(pdf_path: Path) -> int:
    import fitz

    document = fitz.open(pdf_path)
    try:
        return int(document.page_count)
    finally:
        document.close()
