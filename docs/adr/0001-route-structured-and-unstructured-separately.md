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

**The label match is symmetric.** The question has to contain the concept's label, and the label has
to account for most of what the question names. Only the first half was there originally, and
containment on its own turned out not to be identification: *"Wie hoch war Erwerb von Sachanlagen"*
asks about a cash flow and contains the label *"Sachanlagen"*, so the router returned the balance
sheet carrying amount at full confidence with an exact citation on it. A confidently wrong figure
carrying exact provenance is the worst output this system can produce, because the provenance is what
stops a reader checking further.

**Wordings are pooled across the corpus.** Issuers must label their own extension concepts, but
standard IFRS labels come from the official taxonomy, which packages reference rather than bundle.
One filing in this corpus declares no labels at all, which left its 323 tagged facts unreachable by
the structured path. Every wording any filing declares is available to every filing for the same
concept, and each concept scores once on its best-matching wording, so two names for one figure do
not read as ambiguity. Periods still come only from a filing's own facts, so a borrowed wording can
never make the router claim a period the filing does not report.

## Consequences

Measured on 393 generated cases over eight filings:

| | |
|---|---|
| Routing accuracy on tagged figures | 1.000 |
| Answer exact match | 0.963 |
| False answer rate on unanswerable questions | 0.030 |
| Wrong-period traps survived | 1.000 |
| Latency p50 / p95 | 0.7 ms / 3.2 ms |

Wrong-period traps ask for a real concept in a year the filing does not report. The system never
returns a figure for one, which is the property the routing exists to guarantee.

The symmetric label match was chosen by sweeping the threshold rather than asserting one. On the
benchmark alone, anything above 0.5 looks free, and that is an artefact: the answerable questions are
generated as the label verbatim, so they cannot penalise a strict threshold. Judged instead on
hand-written phrasings, 0.6 is where the wrong-figure matches stop and further tightening buys
nothing:

| Minimum question coverage | False answer rate | Natural phrasings still routed | Wrong-figure matches |
|---|---|---|---|
| 0.0 | 0.069 | 5 of 5 | 3 of 3 |
| 0.5 | 0.052 | 4 of 5 | 1 of 3 |
| **0.6** | **0.030** | **3 of 5** | **0 of 3** |
| 0.8 | 0.021 | 3 of 5 | 0 of 3 |

The cost is that the structured path only covers what the filer tagged, which is the primary
statements and any extension concepts they declared. Notes and narrative are the retrieval path's
job, and its quality bounds them.

The second cost is that a question naming more than the concept falls through to retrieval. Asking
for revenue "des Segments Karton" when the filing tags no segment dimension returns passages rather
than the unqualified figure. That is the intended direction: a reader who asked about a segment and
received the group total would have no way to notice.

## Alternatives rejected

**Embed everything, including tables as text.** This is the common approach and it is what the
numbers above argue against. It also makes provenance a prediction, which undermines the one property
this system is built to provide.

**Text-to-SQL over an extracted table store.** A reasonable design for a warehouse, but the tags
already give a queryable fact store with page-accurate provenance, so building a second one would add
an extraction step that can fail without adding capability.

**Let a model decide the route.** Rejected on determinism and explainability. The routing rule is a
few conditions and it can be stated to an auditor in a sentence.

**Dropping a pooled wording when two filings disagree.** Considered while adding pooling, and it
throws away the case pooling exists for. Two issuers wording the same concept differently is normal,
both wordings are things a reader might type, and a wording that reaches two different concepts is
already handled as ambiguous rather than resolved arbitrarily.
