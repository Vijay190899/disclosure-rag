# Decisions

Architecture and tooling decisions, newest first. Anything with a real trade-off gets a full record
under [docs/adr/](docs/adr/), and the summary here links to it.

Superseded rows stay, struck through, with a pointer to what replaced them. A decision log is only
worth keeping if it shows where I changed my mind, so removing the wrong turns would defeat the
purpose.

| Date | Decision | Record |
|---|---|---|
| 2026-07-29 | BM25 is the default retriever. Hybrid loses to it overall and is kept only for queries not using the document's own wording | [ADR-0010](docs/adr/0010-ablation-ladder-results.md) |
| 2026-07-29 | Chunk size must not be dictated by the embedding window. Shrinking chunks to 110 tokens to fit a 128-token model cost recall@1 two thirds | [ADR-0010](docs/adr/0010-ablation-ladder-results.md) |
| 2026-07-29 | M0 probe run. Reconciliation cut at 19 of 50; region-level citations confirmed at 865 of 865, median IoU 0.947 | [ADR-0007](docs/adr/0007-m0-probe-outcome.md) |
| 2026-07-29 | Locate facts through PDF link annotations, not browser geometry. The browser method located 0 of 600 | [ADR-0007](docs/adr/0007-m0-probe-outcome.md) |
| 2026-07-29 | Corpus moves to Austrian filings. The open index carries no German ones, since the Unternehmensregister does not publish into it | [ADR-0007](docs/adr/0007-m0-probe-outcome.md), amending [ADR-0003](docs/adr/0003-esef-corpus-and-labels.md) |
| 2026-07-29 | CI gates on deterministic metrics only; model-judged metrics run nightly and never block a build | [ADR-0006](docs/adr/0006-deterministic-evaluation-gate.md) |
| 2026-07-29 | No agent framework and no MCP server. The answer loop is a fixed pipeline, so an agent adds nondeterminism to a project about verifiability | [ADR-0005](docs/adr/0005-no-agent-framework.md) |
| 2026-07-29 | Provenance is a list of spans carried end to end. Chunking runs over the block list, never over concatenated text | [ADR-0004](docs/adr/0004-provenance-contract.md) |
| 2026-07-29 | Real ESEF filings as the corpus, with Inline XBRL as a mechanical source of numeric and positional labels | [ADR-0003](docs/adr/0003-esef-corpus-and-labels.md) |
| 2026-07-29 | PyMuPDF for parsing. Docling is the named upgrade path if table structure becomes the binding constraint | [ADR-0002](docs/adr/0002-pymupdf-for-parsing.md) |
| 2026-07-07 | ~~Hybrid retrieval over dense-only. Financial documents are full of exact figures and codes that embeddings miss~~ | Tested and largely overturned 2026-07-29. Right about the mechanism, wrong about the conclusion: because exact figures favour lexical matching, fusing a weaker dense retriever in costs ranking positions. See [ADR-0010](docs/adr/0010-ablation-ladder-results.md) |
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

## What the M0 probe changed, later the same day

Three of the decisions above were made in the morning and corrected in the afternoon by measuring
them. Recording that here rather than quietly editing the earlier rows, because the corrections are
the useful part.

**I had the wrong model of how a browser prints.** I assumed an element's position on screen tells
you which printed page it lands on. It does not: printing is a separate layout pass with its own
pagination. The method built on that assumption located 0 of 600 facts. The fix, reading the link
annotations Chromium writes into the PDF, works because those come from the pagination pass itself.

**The most interesting idea in the plan did not survive.** Using tagged statements as an oracle for
figures restated in prose was the argument for including reconciliation, and it needed prose to
restate tagged figures often enough to label a benchmark for free. It does not: 19 of 50, against a
threshold I had written down beforehand. Cut.

**One correction was legitimate and one would not have been.** My first sample drew every untagged
number in the document, including table grids and page footers, which did not match a hypothesis
about prose. Fixing that denominator was right, and moved the result from 15 to 19. Tightening the
filter further would likely have pushed it past 20, and that is where I stopped. Fixing a
measurement that does not match its definition is not the same as tuning one until it agrees with
you, and the pre-registered threshold exists to make the difference visible.

## How I keep this useful

Write the entry the day the choice is made, before knowing whether it was right. Retroactive entries
are reconstructions and they read like it. The trigger is either "I considered two ways of doing
this" or "that surprised me".

Decisions I expect to record while building: chunk size and packing strategy, with the number that
decided it; the fusion method and its parameter; whether reranking earns its latency; the embedding
model, measured on German text; the abstention threshold and the curve it came from; and whichever
of these I get wrong first and have to reverse.
