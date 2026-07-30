# ADR-0004: PyMuPDF for parsing and rendering

- **Status:** Accepted
- **Date:** 2026-07-30

## Context

Everything this system claims rests on knowing where on a page a piece of text sits. The citation
contract promises a page and a region per answer, so the parser decides whether that contract is
deliverable at all.

## Decision

**PyMuPDF.** `page.get_text("dict")` returns blocks, lines and spans each carrying a bounding box, and
the same library renders a page with regions drawn on it.

## Why

- **Geometry is native.** Bounding boxes come out of the parser rather than being reconstructed. This
  is the one requirement that cannot be compromised.
- **The renderer and the parser are the same library.** A coordinate convention mismatch between two
  libraries would be invisible in the metrics and obvious only in the picture, which is the worst
  place for a bug to hide in a system whose output is a picture.
- **Offline, free, deterministic.** No API key, no per-page cost, no network on the hot path. Parse
  output can be cached as test fixtures, so the chunker is testable in CI without credentials.
- **The corpus is born-digital.** These filings are rendered from XHTML, so the text layer is clean.
  Heavier machinery is aimed at scanned documents, which is not the problem here.

## Alternatives rejected

**LlamaParse.** Priced per page, and a 400-page annual report is the normal case. More importantly the
bounding boxes do not survive into the markdown the rest of the pipeline would consume, so it means
paying for geometry and discarding it at the next step.

**ColPali.** Not a parser. It is a late-interaction visual retrieval model that replaces the parse,
chunk and embed pipeline: it removes the chunker, makes lexical fusion impossible because there is no
text to index, and turns "region" from a text box into a patch attention heatmap. Interesting as a
benchmarked alternative, not as a parser.

**PyMuPDF's own table finder**, for recovering cell structure. Tested against 600 tagged facts: every
figure fell inside some detected cell, but the median smallest covering cell was about half a page, so
cells were too coarse to cite, and the column header resolved the period for only 38% of ambiguous
facts. Detection is good on a clean statement page, a 12 by 10 grid with real column labels, and
degrades badly elsewhere, which is where most tagged facts sit. The structured routing in ADR-0001
makes this unnecessary rather than merely difficult.

## Trade-offs accepted

- **Table structure is not reconstructed.** Text blocks with positions, not a grid with header paths.
  This is why figure questions route to the tags instead of being parsed out of the table.
- **Reading order is heuristic** on multi-column pages and will occasionally be wrong.
- **Section hierarchy must be inferred** rather than read off.

Parsing sits behind a `Parser` protocol returning blocks with geometry. **Docling** is the named
upgrade path if table structure ever becomes the binding constraint on the retrieval path.
