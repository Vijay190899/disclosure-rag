# ADR-0003: ESEF filings as the corpus, and Inline XBRL as the label source

- **Status:** Accepted
- **Date:** 2026-07-29
- **Supersedes:** "corpus is public/mock financial filings" in the previous technical documentation

## Context

The previous plan said the evaluation set would be derived from **mock filings**. That is the worst
available option and I should not have written it. Numbers produced against invented documents are
not comparable to anything, and writing my own questions against documents I also wrote is circular
in a way that any competent reviewer would name immediately.

The real constraint is labelling cost. A retrieval benchmark needs relevance judgements, and a
citation benchmark needs something even more expensive: a known correct **region** on a page. Hand
labelling bounding boxes is slow enough that a solo project will produce a few dozen and then stop.

## Decision

The corpus is **real ESEF annual financial reports**, obtained from `filings.xbrl.org`, filtered to
German issuers, with 8 filings in the initial set including one issuer across two consecutive years
so that prior-year comparatives appear naturally.

Labels are **generated mechanically from the Inline XBRL**, not hand written.

## Why this works

Since financial year 2020, issuers on EU regulated markets file the annual financial report under
the European Single Electronic Format (Delegated Regulation (EU) 2019/815). The format is XHTML with
Inline XBRL, and the important property is that the tag is not a sidecar. It wraps the number a
human reads:

```html
<ix:nonFraction name="ifrs-full:Revenue" contextRef="FY2024" unitRef="EUR"
                scale="6" decimals="-6">1,204</ix:nonFraction>
```

Two kinds of ground truth fall out of that:

1. **Semantic.** The concept, value, unit, scale, sign and period are declared by the filer, who is
   legally responsible for them. No extraction, no annotation, no ambiguity about what the number
   means.
2. **Positional.** Because the tag is an element in a rendered document, a headless browser can
   report its geometry. Rendering the filing and reading `getBoundingClientRect()` on every `ix:`
   element produces a bounding box per fact, mechanically, for as many filings as I care to process.

The second is the one that makes this project possible. Region-level citation accuracy is normally
unmeasurable at any scale a solo builder can afford, and here it costs a render.

## The trap I am avoiding

The obvious use of these labels is degenerate. Generating "What was revenue in FY2024?" from a
tagged fact produces a benchmark that asks the system to find a number in a table that I already
know is tagged and already know the location of. It would score well and prove nothing.

**The construction that is worth building: tagged primary statements are the oracle, untagged
narrative prose is the system under test.**

Only the primary statements carry element-level tagging. Notes are block-tagged at best, and the
management report, the highlights page and the narrative discussion restate the same figures in
prose with no tagging at all. So the task becomes: find the figure where it is *not* tagged, and
check it against the tag. The labels are free on one side and the problem stays genuinely hard on
the other.

## Alternatives rejected

**Mock or generated filings.** No external comparability, and self-authored questions grade
themselves. This is what I had, and it was the weakest part of the plan.

**SEC EDGAR.** Unlimited, free, public domain, zero access friction, and I considered it seriously.
Rejected for two reasons. Everyone uses it, so it is the single most saturated corpus in the RAG
portfolio genre. And US filings do not carry the Inline XBRL geometry property in the same
convenient form, which means giving up the mechanical labels that are the entire point.

**Bundesanzeiger and Unternehmensregister.** The richest German source, including unlisted
companies, but bulk access is commercially gated and the terms forbid scraping. Not a foundation to
build a pipeline on.

**Hand-labelled everything.** Roughly 8 hours for 40 questions with verified regions, and it does
not scale past that. It stays as a supplement: the narrative and unanswerable strata still need
human judgement, which is about 60 items and roughly 2 hours. Mechanical labels cover the
exact-figure stratum.

**FinanceBench.** Kept as a planned secondary, run alongside, so there is one externally legible
number that a reader can compare against published work. It does not replace the primary corpus
because it has no positional labels.

## Trade-offs I accept

- **Scope of tagging.** Only primary statements are tagged at element level, so the free labels
  cover a specific and fairly narrow slice. Everything outside it still needs hand labelling.
- **`contextRef` is mandatory to handle correctly.** It resolves period and entity. Getting it wrong
  means scoring prior-year comparatives as current-year figures, which is a silent corruption of the
  entire label set. This is the highest-risk detail in the label plane and it needs a test.
- **Displayed text is not the value.** `1,204` with `scale="6"` is 1204000000. Every comparison has
  to run through normalisation.
- **German documents.** The corpus is largely German, which forces a multilingual embedding model
  and raises compound-noun handling on the lexical side. I count this as a benefit for
  differentiation and a cost in difficulty.
- **The core assumption is unverified.** See ADR risk R1: if narrative prose does not restate enough
  tagged figures, this whole construction is weaker than I think. That is what the M0 probe measures,
  with a written abort threshold, before I build anything on top of it.

## Revisit if

- The M0 probe finds fewer than 20 of 50 sampled narrative figures resolvable. Then reconciliation
  is cut and the corpus argument weakens to "real documents with free retrieval labels", which is
  still better than mock data but no longer distinctive.
- Access to `filings.xbrl.org` becomes unreliable, in which case issuer investor-relations pages
  publish the same ESEF packages directly.
