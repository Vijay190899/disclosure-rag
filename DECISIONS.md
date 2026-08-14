# Decisions

The architectural choices this system rests on, each with a full record under [docs/adr/](docs/adr/)
covering the reasoning, the alternatives rejected, and what would justify revisiting it.

| | Decision | Record |
|---|---|---|
| 1 | Route questions about tagged figures to a structured lookup and everything else to retrieval | [ADR-0001](docs/adr/0001-route-structured-and-unstructured-separately.md) |
| 2 | Real ESEF filings as the corpus, with gold citation labels generated from the tags rather than annotated | [ADR-0002](docs/adr/0002-esef-corpus-and-mechanical-gold-labels.md) |
| 3 | Provenance is a list of spans carried end to end, and a citation points at a figure rather than a block | [ADR-0003](docs/adr/0003-provenance-is-a-list-of-spans.md) |
| 4 | PyMuPDF for parsing and rendering, so geometry is native and the renderer shares the parser's coordinate space | [ADR-0004](docs/adr/0004-pymupdf-for-parsing-and-rendering.md) |
| 5 | BM25 as the retrieval default over hybrid, and no agent framework | [ADR-0005](docs/adr/0005-bm25-default-no-agent-framework.md) |
| 6 | Evaluation is deterministic and reproduces without credentials | [ADR-0006](docs/adr/0006-deterministic-evaluation.md) |
| 7 | An answer records the corpus version that produced it, and can be replayed to prove it | [ADR-0007](docs/adr/0007-answers-are-durable-evidence.md) |

Three of these went against the obvious choice and are worth reading for that reason: routing rather
than embedding everything (1), BM25 rather than hybrid retrieval (5), and no agent framework (5). Each
records the measurement that decided it.

Decision 7 is the one that turns a citation into evidence rather than a screenshot.
