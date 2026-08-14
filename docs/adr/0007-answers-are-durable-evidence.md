# ADR-0007: An answer is evidence only if it can be reproduced later

- **Status:** Accepted
- **Date:** 2026-08-14

## Context

The system's claim is that a reader can verify any answer by looking at the region it came from.
That claim has a second half which is easy to miss and expensive to add afterwards: **the answer has
to still be verifiable later.**

Filings get amended and restated. Indexes get rebuilt with different chunking. Retrievers get
swapped. Six months after an answer was given, "page 25, region (0.630, 0.077)" identifies nothing
unless the thing it pointed into can itself be identified. At that point a citation is a screenshot,
not evidence, and the product's central claim quietly stops being true without anything failing.

## Decision

**Two derived identifiers, and a replay operation.**

A **document version** is the content hash of the source filing. An amended filing gets a new one,
with nothing to remember to increment.

A **snapshot id** is the hash of every document version in the corpus together with the settings that
determine what the index contains: chunk size, overlap, retriever. Change a filing, add one, remove
one, or rechunk, and it moves, because all four change what an answer would be.

Both are **derived, not assigned**. An identifier a human maintains is one that eventually lies.
Documents are sorted before hashing, so load order does not affect the id: one that changes when
nothing did trains people to ignore it, which is worse than not having one.

Every answer carries its snapshot id. With an audit log configured, answers are appended to
append-only JSONL and the answer carries its record id too.

**Any record can be replayed**, with three outcomes:

| Outcome | Meaning |
|---|---|
| `reproduced` | Same snapshot, same answer. The record is still evidence. |
| `superseded` | The corpus or settings moved on. Not a failure, and something an auditor needs stated rather than discovered. |
| `diverged` | The snapshot did not move and the answer did. A defect, and the only outcome that should ever be alarming. |

Superseded results say **which** thing moved: the filing itself, its removal from the corpus, or the
index settings with the filing unchanged. "It is different now" is not useful; "the filing changed
from 65dc9d96 to a3f19b02" is.

## Consequences

- **Timings are excluded from the comparison.** They vary run to run, so including them would report
  every replay as diverged and train people to ignore the one signal that must never be ignored.
- The audit log is **off unless configured**. Writing an audit trail nobody asked for is its own kind
  of surprise, and the ledger directory is mounted read-only in normal operation.
- Ingest became incremental for free: the same content hash that identifies a version also tells the
  builder which filings need rebuilding. A no-op rebuild of eight filings went from minutes of
  headless rendering to 0.53 seconds.
- `/snapshot` exposes what is currently in force, so a client can record it alongside whatever it
  does with an answer.

## Alternatives rejected

**A monotonically increasing build number.** Simple, and it cannot answer "is this the same filing?"
It only answers "was this the same build", which is a different and less useful question when the
concern is whether a document changed underneath a citation.

**Timestamps.** A re-download of identical bytes is not a change, and treating it as one causes
pointless rebuilds and spurious supersessions.

**Storing the retrieved chunks with each answer.** It would make replay unnecessary, and it grows
without bound while proving less: it shows what the system saw, not whether the system would still
say the same thing. Replay against a live pipeline is the stronger check.

## What this does not do

It does not version the *model*. Generation currently runs an extractive implementation with no model
weights involved, so the pipeline version covers it. An LLM generator would need its model and prompt
identifiers folded into the snapshot, and `PIPELINE_VERSION` is the hook for that.
