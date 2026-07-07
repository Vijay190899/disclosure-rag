# ADR-0001: Record architecture decisions

- **Status:** Accepted
- **Date:** 2026-07-07

## Context

I want a record of *why* the important technical choices on this project were made, not just what they were. Six weeks from now (or in an interview) I don't want to be reverse-engineering my own reasoning.

## Decision

I'll keep short Architecture Decision Records in `docs/adr/`, numbered sequentially, and a one-line summary of each in `DECISIONS.md` at the repo root. Each ADR captures the context, the decision, and the trade-offs I accepted. Format kept deliberately light so I actually write them.

## Consequences

- Decisions are reviewable in the git history alongside the code that implements them.
- Doubles as interview prep: every ADR is a story about a trade-off I reasoned through.
- Small ongoing cost: one short file per non-trivial decision.
