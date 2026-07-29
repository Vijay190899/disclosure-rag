# ADR-0007: M0 probe outcome, and what it changed

- **Status:** Accepted
- **Date:** 2026-07-29
- **Amends:** [ADR-0003](0003-esef-corpus-and-labels.md) on the corpus and on the label mechanism
- **Evidence:** [spikes/esef_probe/REPORT.md](../../spikes/esef_probe/REPORT.md)

## Context

[ADR-0003](0003-esef-corpus-and-labels.md) committed to real ESEF filings with labels generated
mechanically from Inline XBRL. Two assumptions underneath it had been asserted and not measured, so
M0 existed to test them against real documents before anything was built on top.

The probe ran against three Austrian ESEF filings containing 865 tagged numeric facts. It found
three things, and all three changed the plan.

## Finding 1: there are no German filings in the open index

`filings.xbrl.org` returns zero results for Germany. Measured on 2026-07-29:

| Country | Filings | Country | Filings |
|---|---|---|---|
| DK | 2126 | IT | 872 |
| SE | 1415 | BE | 706 |
| FR | 1176 | NL | 656 |
| FI | 1168 | AT | 600 |
| NO | 958 | ES | 542 |
| PL | 877 | **DE** | **0** |

Germany's officially appointed mechanism is the Unternehmensregister, which is commercially gated
and does not publish into the open index that this service aggregates. ADR-0003 already recorded
that the Bundesanzeiger route was closed for bulk access. What I had not realised is that this also
removes German filings from the aggregator, so the "filter to German issuers" step was not
executable at all.

**Decision: Austria becomes the primary corpus.** Austrian filings are German-language, so the
argument about compound nouns and multilingual embeddings survives intact, and the ESEF and Inline
XBRL mechanics are identical because they come from an EU regulation rather than a national one.
The country list is a parameter, so widening to the larger Nordic and French indices is a one-line
change if more documents are needed.

What is lost is small but should be named: I can no longer say "German filings from the
Bundesanzeiger", and a German interviewer may know the Unternehmensregister gap. Being able to
explain why the corpus is Austrian is a better answer than having quietly used a German-sounding
one.

## Finding 2: browser geometry does not survive printing

The planned mechanism was to read `getBoundingClientRect()` on each tagged element and derive a page
index by dividing the vertical offset by a fixed page height. **It located 0 of 600 facts.**

The mental model was wrong. Screen layout and print layout are different layouts. Chromium
repaginates when printing, so an element's scroll offset in the viewport says nothing about which
printed page it lands on. On one filing the arithmetic predicted pages 22 to 67 for a document that
printed to 184 pages, and the drift grew through the document.

**Decision: locate facts through PDF link annotations instead.** Each tagged fact is wrapped in an
anchor before rendering. Chromium preserves anchors through print-to-PDF as link annotations, and
each annotation carries the page number and a rectangle in PDF coordinate space. Those are emitted
by the same pagination pass that produces the pages, so they cannot disagree with it.

Results, verified independently by searching each annotated page for the fact's displayed text and
comparing rectangles:

| Measure | Threshold | Result |
|---|---|---|
| Facts located | not set | **865 of 865 (100%)** |
| Located boxes confirmed by text search | 90% | **600 of 600 (100%)** |
| Median IoU against the text-search box | 0.5 | **0.947** |

A2 passes, and passes by a wide margin. Region-level citation accuracy is measurable, so citation
IoU stays as the project's headline metric.

## Finding 3: narrative prose does not restate enough tagged figures

**A1 fails: 19 of 50, against a threshold of 20.** The automated resolver is deliberately generous
because it matches on normalised value, so it counts coincidences as hits. The hand-confirmed count
can therefore only be lower than 19.

**Decision: M4 reconciliation is cut**, per the rule fixed before the probe ran.

One methodological correction along the way, recorded because the distinction matters. The first
sampler drew every untagged number anywhere in the document, which pulled in untagged table grids,
the table of contents, page footers and the sustainability section. A1 is a claim about *prose*, so
that denominator did not match the hypothesis. Adding a sentence-level prose filter (of 10738
untagged mentions, 1329 sit in prose sentences) moved the result from 15 to 19.

I stopped there. The filter still admits some table rows and tightening it further would probably
push the number past 20. That is the difference between fixing a measurement that did not match its
definition, which is legitimate, and tuning a measurement until it gives the answer I wanted, which
is what the pre-registered threshold exists to prevent.

The capability is not worthless, and real instances exist:

> "Die Gesamtaktiva der Addiko Gruppe beliefen sich zum Jahresende 2022 auf EUR 5.996,4 Mio"

which resolves cleanly to `ifrs-full:Assets`. There are simply not enough of them to build a
labelled benchmark for free, which was the entire argument for including reconciliation in v1.

## Consequences

- The project is **disclosure location with verifiable citations**, not numeric reconciliation.
- The headline claim is unchanged and is now evidence-backed on the labelling side: citation
  accuracy is measurable at scale without hand annotation.
- The fact ledger keeps its role as gold labels for citation IoU and as an exact-answer store for
  numeric questions. It loses its role as an oracle for checking prose.
- Roughly a week of M4 work is not spent, on the strength of an afternoon's measurement.

## What would bring reconciliation back

- A corpus where the notes are element-tagged rather than block-tagged, which would raise the share
  of resolvable figures.
- Accepting hand annotation for the reconciliation set, which is viable at 30 to 50 pairs but is a
  different proposition from free labels and needs to be scoped as such.
- A sharper prose and claim extractor that finds figures my regex sampler misses. Worth revisiting
  only with a fresh sample and the threshold fixed again in advance.
