# Decisions

Architecture and tooling decisions, newest first. Anything with a real trade-off gets a full record
under [docs/adr/](docs/adr/), and the summary here links to it.

Superseded rows stay, struck through, with a pointer to what replaced them. A decision log is only
worth keeping if it shows where I changed my mind, so removing the wrong turns would defeat the
purpose.

| Date | Decision | Record |
|---|---|---|
| 2026-07-29 | CI gates on deterministic metrics only; model-judged metrics run nightly and never block a build | [ADR-0006](docs/adr/0006-deterministic-evaluation-gate.md) |
| 2026-07-29 | No agent framework and no MCP server. The answer loop is a fixed pipeline, so an agent adds nondeterminism to a project about verifiability | [ADR-0005](docs/adr/0005-no-agent-framework.md) |
| 2026-07-29 | Provenance is a list of spans carried end to end. Chunking runs over the block list, never over concatenated text | [ADR-0004](docs/adr/0004-provenance-contract.md) |
| 2026-07-29 | Real ESEF filings as the corpus, with Inline XBRL as a mechanical source of numeric and positional labels | [ADR-0003](docs/adr/0003-esef-corpus-and-labels.md) |
| 2026-07-29 | PyMuPDF for parsing. Docling is the named upgrade path if table structure becomes the binding constraint | [ADR-0002](docs/adr/0002-pymupdf-for-parsing.md) |
| 2026-07-07 | Hybrid retrieval over dense-only. Financial documents are full of exact figures and codes that embeddings miss | Still holds, but reclassified as a hypothesis until it has a delta row. See [ADR-0006](docs/adr/0006-deterministic-evaluation-gate.md) |
| 2026-07-07 | ~~OpenAI Agents SDK for the answer loop, retrieval exposed via MCP~~ | Superseded 2026-07-29 by [ADR-0005](docs/adr/0005-no-agent-framework.md) |
| 2026-07-07 | Adopt lightweight ADRs | [ADR-0001](docs/adr/0001-record-architecture-decisions.md) |

## What changed on 2026-07-29, and why

Reviewing the plan before starting to build turned up three things worth naming, because they are
the kind of mistake that is cheap to fix on paper and expensive to fix in code.

**A slash is not a decision.** I had written "LlamaParse / ColPali" in three documents. Looking
properly showed they are not comparable options: one is a parsing API, the other is a retrieval
model that would have deleted my chunker and made hybrid retrieval impossible. The formatting hid an
open question underneath a contract that assumed it was closed.

**I had described the finished system as though it existed.** "CI fails if these regress" described
an evaluation gate that was not built. That was the one claim in the documents that was falsifiable
rather than merely aspirational, so it was the one that had to go first.

**The interesting problem was not the one I had written down.** The plan was a general document
question-answering system, which is the most common portfolio project there is. The specific thing
worth building is narrower: a retrieval system can produce a correct answer while citing the wrong
place, standard evaluation cannot see it, and Inline XBRL makes it measurable without hand
annotation. Everything else in the design now follows from that.

## How I keep this useful

Write the entry the day the choice is made, before knowing whether it was right. Retroactive entries
are reconstructions and they read like it. The trigger is either "I considered two ways of doing
this" or "that surprised me".

Decisions I expect to record while building: chunk size and packing strategy, with the number that
decided it; the fusion method and its parameter; whether reranking earns its latency; the embedding
model, measured on German text; the abstention threshold and the curve it came from; and whichever
of these I get wrong first and have to reverse.
