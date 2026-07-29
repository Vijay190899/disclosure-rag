# ADR-0004: Provenance is a list of spans carried end to end

- **Status:** Accepted
- **Date:** 2026-07-29
- **Supersedes:** the `{document_id, page, bbox}` citation shape in the previous interface contract

## Context

The product claim is that a reader can verify any answer in one click. That requires knowing which
region of which page a piece of retrieved text occupies, and keeping that knowledge intact all the
way from the parser to the JSON response.

Two defects in the previous design, both of which would have surfaced late and cost real rework.

**One box per citation cannot express the motivating example.** The previous contract gave each
citation a single `page` and a single `bbox`. A chunk assembled from several blocks occupies several
regions. A financial table that continues across a page break occupies regions on two pages. That is
not an exotic case: it is the exact scenario the README opens with. The schema could not represent
the thing the project exists to do.

**The chunker silently destroys the link.** This is the more dangerous one, because it is invisible
until you look for it. The natural way to write a chunker is to concatenate block text into one
string and run a splitter over it. The moment that concatenation happens, chunk offsets no longer
correspond to any block, and the mapping back to a bounding box is gone. It cannot be recovered
afterwards. Every citation degrades to "somewhere in this passage", which is precisely the vague
behaviour I criticise in the README.

## Decision

**Provenance is a first-class type and a list, from parse to response.**

```
Span   = { page: int, x0: float, y0: float, x1: float, y1: float }   # normalised to the page box
Block  = { text: str, span: Span, order: int }
Chunk  = { chunk_id, text, spans: list[Span], parent_id: str | None, token_count }
Citation = { document_id, chunk_id, spans: list[Span], quote: str }
```

Three rules follow from this and they are not negotiable:

1. **The chunker operates on the block list, never on a concatenated string.** Blocks are packed in
   reading order up to a token budget, and each chunk carries the spans of the blocks that formed
   it.
2. **Coordinates are normalised to the page box**, so a change of render DPI does not invalidate a
   stored index.
3. **A span list is never flattened to a single box**, not in the store, not in the API, not in the
   viewer. Where a single region is genuinely needed for display, the union is computed at the point
   of rendering and is not persisted.

## Why this is decided now rather than discovered later

This is the most expensive decision in the project to reverse. It touches the parser output, the
chunker, the vector store payload schema, the API response model and the viewer. Changing it after
ingestion means re-ingesting the whole corpus and breaking the API at the same time. Changing it now
costs the time it took to write this file.

It also determines whether the headline metric is possible at all. Citation IoU against the ledger's
gold boxes requires a predicted region to compare. Without multi-span provenance there is nothing
meaningful to compute an intersection over.

## Trade-offs I accept

- **Larger payloads.** Every chunk stores a list rather than five numbers. At this corpus size the
  cost is irrelevant, and if it ever matters, spans compress well.
- **The chunker is harder to write.** Packing blocks under a token budget while preserving reading
  order is more work than calling a text splitter. This is the correct place to spend that
  complexity, because it is the one place where losing information is irreversible.
- **Quote extraction is a separate problem.** Having the spans of a chunk does not give a
  sub-sentence highlight for a specific claim. Claim-level span attribution is M5 work and is
  scoped as a stretch, not implied by this contract. The README says region, and region means the
  block regions a chunk covers.

## Consequences

- Section 6 of the technical documentation carries a same-change-set rule, because everything
  downstream couples to this shape.
- The `/page/{document_id}/{page}.png` endpoint takes a list of spans.
- Any parser placed behind the `Parser` protocol must emit geometry. A parser that cannot is
  disqualified regardless of its other merits, which is part of why ADR-0002 came out the way it
  did.

## Revisit if

- Claim-level attribution lands and sub-block spans become necessary, in which case `Span` gains an
  optional character range within its block rather than changing shape.
- A retrieval approach without text chunks is adopted, which would make this contract meaningless
  and require a new one.
