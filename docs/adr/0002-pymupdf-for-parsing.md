# ADR-0002: PyMuPDF for parsing, not LlamaParse or ColPali

- **Status:** Accepted
- **Date:** 2026-07-29
- **Supersedes:** the "LlamaParse / ColPali" phrasing in the previous README, STACK.md and technical
  documentation

## Context

Everything this project claims rests on being able to say where on a page a piece of text sits. The
citation contract in section 7 of the technical documentation promises a page and a region per
claim, so the parser is not a detail: it decides whether that contract is deliverable at all.

I had written "LlamaParse / ColPali" in three documents as though they were two brands of the same
thing. Writing this ADR is what made me look properly, and they are not comparable. They are not
even at the same layer:

- **LlamaParse** is a hosted parsing API. PDF in, markdown or JSON out. It feeds a conventional
  text pipeline: chunk, embed, retrieve, cite.
- **ColPali** is a retrieval model. It embeds page images as multi-vector representations and scores
  them with late interaction. It does not parse. It **replaces** the parse, chunk and embed pipeline
  with something structurally different.

Choosing ColPali is not swapping a component. It deletes the chunker, makes BM25 fusion impossible
because there is no text to index, leaves a text cross-encoder with nothing to rerank, and turns
"region" from a text bounding box into a patch attention heatmap. It would invalidate the hybrid
retrieval decision recorded in DECISIONS.md, which is the decision I am most confident about.

So the slash was not a shorthand. It was an undecided decision formatted as a decision, and it was
sitting underneath a contract that assumed one of the two branches.

## Decision

**PyMuPDF.** The serving plane parses the rendered PDF with `page.get_text("dict")`, which returns
blocks, lines and spans each carrying a bounding box.

## Why

- **Geometry is native.** Bounding boxes come out of the parser rather than being reconstructed.
  This is the single requirement I cannot compromise on.
- **It renders as well as parses.** The same library draws rectangles on a page and exports the
  image, which is exactly what the `/page` endpoint and the citation viewer need. The screenshot
  that demonstrates the project becomes a by-product of the pipeline rather than something mocked
  up separately.
- **Offline, free and deterministic.** No API key, no per-page cost, no network on the hot path.
  That matters more than it sounds: it means parse output can be cached as test fixtures and the
  chunker is testable in CI without credentials.
- **The corpus is already digital.** These filings are rendered from XHTML, so the text layer is
  clean. Heavy parsing machinery is aimed at scanned documents, which is not the problem here.

## Alternatives rejected

**LlamaParse.** Priced per page, and a 400-page annual report is the motivating example, so
ingestion has a real cost and a real wall-clock time. More importantly the bounding boxes do not
survive into the markdown that the rest of the pipeline would consume. I would be paying for
geometry and then discarding it at the next step.

**ColPali.** Covered above. It is a genuinely interesting model and the right way to use it here is
as a benchmarked alternative in a later ablation, measured on the same question set, and not as a
fork in the v1 plan.

**Docling.** The closest call, and the named upgrade path. It is open, emits geometry, and does
better structural table reconstruction than PyMuPDF. I am not starting with it because PyMuPDF is
simpler and I do not yet know that table structure is the binding constraint. That is a measurement,
not a guess, and M2 will produce it.

## Trade-offs I accept

- **Table structure is weaker.** PyMuPDF gives me text blocks with positions, not a reconstructed
  table with header paths. For reconciliation I need to know which column a number sits under, and
  block geometry alone may not be enough. This is the most likely reason I end up moving to Docling.
- **Reading order is heuristic** on multi-column pages and will occasionally be wrong.
- **No semantic structure.** Section hierarchy has to be inferred rather than read off.

Per principle P6, the parser sits behind a `Parser` protocol returning a list of blocks with
geometry. Moving to Docling should be an afternoon, and if it is not, the seam was wrong.

## Revisit if

- Table header reconstruction turns out to be the limiting factor on reconciliation accuracy in M4.
- Scanned or image-only filings enter the corpus, where PyMuPDF has no text layer to read and the
  case for a visual model becomes real.
- The reading-order heuristic produces enough failures in the M2 taxonomy to show up as a named
  class rather than a handful of one-offs.
