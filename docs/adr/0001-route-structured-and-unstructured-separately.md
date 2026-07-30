# ADR-0001: Route tagged figures to a structured lookup, everything else to retrieval

- **Status:** Accepted
- **Date:** 2026-07-30

## Context

EU issuers file annual reports under ESEF, which is XHTML carrying Inline XBRL. The machine-readable
tag wraps the number a human reads, so the filing itself declares each figure's concept, value, unit,
period and position on the page.

That changes what the right architecture is. A question about a tagged figure has an exact answer at
a known location. The default approach, embedding the whole document and letting a vector search plus
a language model recover the number, is measurably worse on this corpus:

- Retrieval puts the right passage first for 35% of figure questions, so most of the time the model
  would be reading from the wrong passage.
- A statement row carries several periods' values side by side, and the column header that
  distinguishes them sits in a different text block. Once the page is linearised into text, nothing
  in the retrieved passage says which value belongs to which year.
- The citation becomes a prediction. A reader who has to verify a figure needs to know where it came
  from, and a predicted region is only as good as the retrieval that produced it.

## Decision

Route on question type.

**A question naming a tagged concept and a period goes to the fact ledger.** The answer is the tagged
value; the citation is the tag's own bounding box. Both are exact rather than estimated, and the
response marks the citation `exact=true` so no downstream consumer treats it as a prediction.

**Everything else goes to retrieval** with a span-attributed answer.

**Anything insufficiently supported abstains** and returns the nearest evidence instead of a guess.

Routing is deterministic. A model in front of a database lookup adds latency and a failure mode in
exchange for nothing, and the routing decision has to be explainable when a citation is challenged.

Both a concept and a period are required. A concept without a period is ambiguous across years, which
is precisely the ambiguity that makes the text path unreliable, so it falls through to retrieval
rather than guessing a year.

## Consequences

Measured on 120 generated cases:

| | |
|---|---|
| Routing accuracy on tagged figures | 0.983 |
| Answer exact match | 0.950 |
| Wrong-period traps survived | 1.000 |
| Latency p50 / p95 | 1.3 ms / 2.3 ms |

Wrong-period traps ask for a real concept in a year the filing does not report. The system never
returns a figure for one, which is the property the routing exists to guarantee.

The cost is that the structured path only covers what the filer tagged, which is the primary
statements and any extension concepts they declared. Notes and narrative are the retrieval path's
job, and its quality bounds them.

## Alternatives rejected

**Embed everything, including tables as text.** This is the common approach and it is what the
numbers above argue against. It also makes provenance a prediction, which undermines the one property
this system is built to provide.

**Text-to-SQL over an extracted table store.** A reasonable design for a warehouse, but the tags
already give a queryable fact store with page-accurate provenance, so building a second one would add
an extraction step that can fail without adding capability.

**Let a model decide the route.** Rejected on determinism and explainability. The routing rule is two
conditions and it can be stated to an auditor in a sentence.
