"""Draw cited regions onto a document page.

The same library that parsed the geometry renders it, so the outline lands where
the parser said the text was. If these were two different libraries a coordinate
convention mismatch would be invisible in the numbers and obvious only in the
picture.
"""

from __future__ import annotations

from pathlib import Path

from disclosure_rag.provenance import Span

OUTLINE = (0.85, 0.1, 0.1)  # red, visible on white paper without obscuring text
OUTLINE_WIDTH = 1.4
PADDING = 0.004  # a little air around a tight numeric box, in page fractions


def parse_regions(raw: str, page: int) -> list[Span]:
    """Parse ``x0,y0,x1,y1;x0,y0,...`` into spans.

    The wire format a ``/query`` citation hands straight back to ``/page``.
    """
    spans: list[Span] = []
    for part in raw.split(";"):
        cleaned = part.strip()
        if not cleaned:
            continue
        pieces = cleaned.split(",")
        if len(pieces) != 4:
            raise ValueError(f"region must be x0,y0,x1,y1, got {cleaned!r}")
        try:
            x0, y0, x1, y1 = (float(value) for value in pieces)
        except ValueError as error:
            raise ValueError(f"region values must be numbers, got {cleaned!r}") from error
        spans.append(Span(page=page, x0=x0, y0=y0, x1=x1, y1=y1))
    return spans


def render_page_with_regions(pdf_path: Path, page: int, regions: str, dpi: int = 110) -> bytes:
    """Return a PNG of one page with the given regions outlined."""
    import fitz

    spans = parse_regions(regions, page)
    document = fitz.open(pdf_path)
    try:
        if page < 0 or page >= document.page_count:
            raise IndexError(f"page {page} outside 0..{document.page_count - 1}")
        target = document[page]
        width, height = target.rect.width, target.rect.height

        for span in spans:
            rect = fitz.Rect(
                max(span.x0 - PADDING, 0.0) * width,
                max(span.y0 - PADDING, 0.0) * height,
                min(span.x1 + PADDING, 1.0) * width,
                min(span.y1 + PADDING, 1.0) * height,
            )
            annotation = target.add_rect_annot(rect)
            annotation.set_colors(stroke=OUTLINE)
            annotation.set_border(width=OUTLINE_WIDTH)
            annotation.update()

        pixmap = target.get_pixmap(dpi=dpi)
        return bytes(pixmap.tobytes("png"))
    finally:
        document.close()
