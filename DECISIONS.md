# Decisions

A running log of the architecture and tooling decisions I make on this project, newest first. Anything with real trade-offs gets a full record under [docs/adr/](docs/adr/).

| Date | Decision | Notes |
|---|---|---|
| 2026-07-07 | Adopt lightweight ADRs | See [ADR-0001](docs/adr/0001-record-architecture-decisions.md). |
| 2026-07-07 | Hybrid retrieval over dense-only | Financial docs are full of exact figures and codes that embeddings miss; BM25 + rerank covers the gap. |
| 2026-07-07 | OpenAI Agents SDK for the answer loop | Single focused agent — the SDK is the right weight; retrieval exposed via MCP. |

_Add a row when you make a call worth remembering. Promote it to a full ADR when the trade-off is non-obvious._
