# ADR-0003: Provenance is a list of spans, and a citation points at a figure

- **Status:** Accepted
- **Date:** 2026-07-30

## Context

The product claim is that a reader can verify any answer in one click. That requires knowing which
region of which page a piece of text occupies, and keeping that knowledge intact from the parser to
the JSON response.

Two things make that harder than it sounds.

**A chunker destroys provenance by default.** The natural implementation concatenates block text into
one string and runs a splitter over it. The moment that join happens, offsets no longer correspond to
any block and the mapping back to a region cannot be recovered. Every citation degrades to "somewhere
in this passage".

**A block is not a citation.** A tagged figure occupies about 0.00026 of a page; the text block
containing it occupies about 0.0175, roughly seventy times more. A citation at block granularity
contains the answer but does not point at it, and any metric comparing the two measures the size
difference rather than the quality of the citation.

## Decision

**Provenance is a first-class type and a list, end to end.**

```
Span     = { page, x0, y0, x1, y1 }        # normalised to the page box
Block    = { text, span, order }
Chunk    = { chunk_id, text, spans: list[Span], token_count }
Citation = { document_id, page, spans: list[Span], quote, exact }
```

Three rules follow and none are negotiable:

1. **The chunker operates on the block list, never on concatenated text.** Blocks are packed in
   reading order up to a token budget and each chunk carries the spans of the blocks that formed it.
2. **Coordinates are normalised to the page box**, so changing render resolution does not invalidate a
   stored index.
3. **A span list is never flattened.** Where a viewer needs one rectangle, the union is computed at
   render time and not persisted.

**A citation points at a figure, not a block.** `citation.py` narrows a retrieved passage to the
numeric tokens on the line that best matches the query. On the structured path the citation is the
tag's own box, marked `exact=true`.

A list rather than a single box because a chunk assembled from several blocks occupies several
regions, and a table continuing across a page break occupies regions on two pages. That is the
motivating case, not an edge case.

## Consequences

- This is the most expensive decision in the project to reverse: it touches the parser, the chunker,
  the store payload, the API contract and the viewer. Changing it after ingestion means re-ingesting
  the corpus and breaking the API at once.
- It is also what makes the headline metric possible. Citation IoU against the tags' boxes needs a
  predicted region of comparable size to compare against.
- Any parser placed behind the `Parser` protocol must emit geometry. One that cannot is disqualified
  regardless of its other merits, which is part of why ADR-0004 came out the way it did.
- Where a block must be split because it exceeds the chunk budget on its own, every piece keeps the
  whole block's span. The text genuinely is inside that region, so the citation stays truthful and
  only its tightness suffers, which is the right place for the cost to land.

## Trade-offs accepted

- **Larger payloads.** A list rather than five numbers per chunk. Irrelevant at this corpus size and
  compressible if it ever is not.
- **A harder chunker.** Packing blocks under a budget while preserving reading order is more work than
  calling a text splitter. This is the correct place to spend that complexity, because it is the one
  place where losing information is irreversible.
- **Sub-sentence attribution is not solved.** Having a chunk's spans does not give a per-claim
  highlight. Figure-level citation covers the structured path; claim-level attribution on the
  narrative path is future work.
