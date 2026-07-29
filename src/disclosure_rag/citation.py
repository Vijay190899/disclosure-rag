"""Narrow a retrieved passage down to the figure it is being cited for.

This module is why the label plane pays for itself, and it exists because the
evaluation harness was measuring nothing without it.

The problem it fixes. Citations used to be the region of the retrieved chunk,
which is a text block or several. A gold fact is a number, about 0.00026 of a
page; a block is about 0.0175, roughly seventy times larger. At that granularity
"does the citation contain the gold box" is satisfied by any block on the right
part of the page, so citation coverage came out identical to rank-1 recall by
construction, and **page-level gold would have scored the same**. The 865 located
facts and their median IoU of 0.947 were bought and never spent.

Narrowing the citation to the number restores the measurement. Predicted and gold
regions become comparable in size, so intersection over union means something
again, and the precision of the label plane finally shows up in the score.

It is also what makes the product honest. A reader asking where a figure came
from wants the figure outlined, not the paragraph around it.
"""

from __future__ import annotations

import re
from pathlib import Path

from disclosure_rag.ingest.chunker import Chunk
from disclosure_rag.provenance import Span
from disclosure_rag.retrieval.lexical import tokenize

# Identifies a token as a figure. Deliberately permissive about format: the job
# here is "is this a number", not "is this well-formed grouping", and the digit
# count below does the filtering.
#
# The first version required grouped thousands, so it rejected any plain run of
# four or more digits. That silently excluded "2022" and any ungrouped figure
# like "1204", both of which appear throughout these filings, and a test caught
# it only because the year case was written down explicitly.
NUMBER = re.compile(r"^-?\(?\d[\d.,]*\)?$")

# Below this many digits a figure carries too little information to be worth
# citing as the answer. Page numbers and note references live here.
MIN_DIGITS = 2


def looks_numeric(word: str) -> bool:
    stripped = word.strip().strip("()")
    if not NUMBER.match(word.strip()):
        return False
    return sum(character.isdigit() for character in stripped) >= MIN_DIGITS


def _page_words(pdf_path: Path, page_number: int) -> list[tuple[str, Span]]:
    """Word boxes for one page.

    Read at citation time rather than stored on every chunk. Word-level geometry
    would multiply the index size for something only needed on the handful of
    passages actually cited.
    """
    import fitz

    document = fitz.open(pdf_path)
    try:
        if page_number >= document.page_count:
            return []
        page = document[page_number]
        width, height = page.rect.width, page.rect.height
        return [
            (
                word[4],
                Span.from_rect(page_number, word[0], word[1], word[2], word[3], width, height),
            )
            for word in page.get_text("words")
        ]
    finally:
        document.close()


def _overlaps(outer: Span, inner: Span) -> bool:
    """True if inner sits inside outer, allowing for a small rendering margin."""
    return outer.covers(inner) >= 0.5


def select_numeric_spans(
    pdf_path: Path,
    chunk: Chunk,
    query: str,
    max_spans: int = 3,
) -> list[Span]:
    """Pick the figures within a retrieved chunk that the query is asking about.

    Deliberately a simple, deterministic rule rather than a model: the words of
    the query that also appear in the chunk anchor a line, and the numbers on
    that line are the candidates. A financial statement row puts its label and
    its values on one line, which the M2 run confirmed on real documents, so this
    is the mechanism that row structure actually offers.

    Its limitation is the honest one to state: on a row carrying several periods
    it cannot choose between them, because the column header that distinguishes
    them is not on the line. That is the open finding, not a bug in this
    function, and returning the candidates rather than guessing one keeps the
    ambiguity visible in the metric instead of hiding it behind a coin flip.
    """
    query_terms = {term for term in tokenize(query) if len(term) > 3 and not term.isdigit()}
    if not query_terms:
        return []

    candidates: list[Span] = []
    for page in chunk.pages:
        words = [
            (text, span)
            for text, span in _page_words(pdf_path, page)
            if any(_overlaps(region, span) for region in chunk.spans if region.page == page)
        ]
        if not words:
            continue

        # Group into lines by vertical position, the granularity a table row uses.
        lines: dict[int, list[tuple[str, Span]]] = {}
        for text, span in words:
            lines.setdefault(round(span.y0 * 400), []).append((text, span))

        best_line: list[tuple[str, Span]] | None = None
        best_overlap = 0
        for line in lines.values():
            line_terms = {term for text, _ in line for term in tokenize(text)}
            overlap = len(query_terms & line_terms)
            if overlap > best_overlap:
                best_overlap, best_line = overlap, line
        if best_line is None:
            continue

        candidates.extend(span for text, span in best_line if looks_numeric(text))

    return candidates[:max_spans]
