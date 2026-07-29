# ADR-0009: What the first baseline measured, and two things it caught

- **Status:** Accepted
- **Date:** 2026-07-29
- **Amends:** the metric definition in section 9 of the technical documentation
- **Evidence:** 843 chunks and 120 questions over three Austrian ESEF filings

## Context

M2 ran the first end-to-end measurement: ingest the rendered document, chunk it
with spans preserved, retrieve with BM25, and score the result against the gold
spans from the label plane.

The headline number is **0.000 across every column**. Both times the run
produced that, it was the measurement at fault rather than the system, and the
two causes are worth recording separately because only one of them is fixed.

## Finding 1: IoU is the wrong metric here, and coverage is the right one

The first version scored citations with intersection over union at a 0.5
threshold, following the plan in section 9.

IoU compares two regions of comparable size. These are not comparable. Measured
on the corpus:

| | Mean area, as a fraction of a page |
|---|---|
| Gold fact, a tagged number | 0.00026 |
| Citation, the text block containing it | 0.0175 |

A perfectly correct citation therefore scores an IoU of roughly 0.015. The
threshold was unreachable by construction, so the metric was measuring the size
difference between a number and a paragraph rather than whether the citation was
any good.

**Decision: score citations by containment.** `Span.covers` returns the fraction
of the gold region falling inside a cited region, and a citation counts as
correct at 0.5 or above. The question a reader actually asks is "if I look where
it pointed, will I find the number?", and that is containment, not overlap.

Under containment the same run finds 60 of 60 sampled gold facts covered by some
chunk, so the pipeline was working the whole time.

**Coverage alone is gameable**, because citing an entire page always contains the
answer and helps nobody. So `mean_tightness` is reported beside it: the share of
the cited region that is actually the answer. It is low now, by design, since
citations are block-level. It is the headroom number, and it should rise when
citations become claim-level in M5.

IoU is kept in `provenance.py` and still used where the two regions genuinely are
comparable, such as the label plane confirming its own boxes against a text
search.

## Finding 2: the exact-figure questions are unanswerable, and it is my fault

With the metric fixed, the baseline was still 0.000. The cause is the question
generator, not the retriever.

Questions are built mechanically from XBRL concept names, so they come out in
English: "What was interest revenue calculated using effective interest method
for the period 2022-01-01 to 2022-12-31?". The documents are Austrian and the
corresponding row reads "Zinserträge unter Anwendung der Effektivzinsmethode
192,9 185,5".

There is no shared vocabulary. Lexical retrieval cannot bridge that, so it
matches on whatever else the query contains, mostly the year.

Confirmed directly, retrieving the chunk that covers the gold fact:

| Query | Rank of the covering chunk |
|---|---|
| English concept question, as generated | not in top 50 |
| The German label as printed in the document | **4** |
| The figure itself, "192,9" | **1** |

So the ingest, chunking, span propagation and scoring are all sound. The
question set is the broken part.

**Decision: questions are generated from the German label the issuer declares
for each concept**, read from the taxonomy label linkbase that ships inside the
ESEF report package. A concept with no declared label is skipped rather than
asked about in English, because such a question is unanswerable by construction
and would depress the score for a reason unrelated to retrieval.

The probe's fetcher had been discarding the linkbases, keeping only the report
and its stylesheets, so the corpus was fetched again.

### The baseline this produced

| Stratum | n | recall@1 | recall@5 | recall@10 | coverage@1 | shown first when found | tightness |
|---|---|---|---|---|---|---|---|
| exact figure | 117 | 0.231 | 0.462 | 0.538 | 0.231 | 0.429 | 0.025 |

The number worth reading is the second from last. When the answer is retrieved
anywhere in the top ten, it is ranked first only 43% of the time. On the rest,
the system holds the right passage and shows the reader a different one. That is
the failure this project was built to expose, and it is invisible to
answer-level scoring.

Tightness of 0.025 means a citation is roughly forty times the area of the
number it points at, which is what block-level citation costs and what
claim-level attribution in M5 should improve.

A note on label availability, since it limits the corpus. Issuers must declare
labels for their own extension concepts, but standard IFRS labels live in the
official taxonomy, which packages reference rather than bundle. Coverage
therefore varies: 92 of 92 concepts for one filing, 84 of 107 for another, and
19 of 94 for a third that bundled only its extensions. Loading the official IFRS
German labels would fix the gap and is the obvious next corpus improvement.

I considered using the document's own row label as the question text, since it
is right there in the same block. Rejected: the row label sits in the same block
as the answer, so a query built from it is close to handing the retriever the
target. That is the degenerate-benchmark trap from ADR-0003 in another costume.

## A note on what this run did establish

Not everything is pending. The run confirmed several things that were previously
assertions:

- Blocks keep a table row intact. The row label and its figures arrive in one
  block, "Zinserträge unter Anwendung der Effektivzinsmethode 192,9 185,5",
  which is the layout property the whole citation idea depends on. I had
  expected to find labels and values split apart, and they are not.
- Span propagation survives chunking end to end, on real documents rather than
  fixtures: every gold fact is contained by some chunk.
- The gold spans, produced from the stamped render, line up with chunks parsed
  from the plain render. The two renders agree on pagination, 184 pages each.
- Retrieving on the figure itself ranks the right chunk first, which is direct
  evidence for the hybrid retrieval argument in DECISIONS.md. It stays a
  hypothesis until it has a delta row, but it is now a hypothesis with something
  behind it.

## Consequences

- Section 9 of the technical documentation now specifies coverage and tightness
  rather than citation IoU.
- The first honest baseline number waits on the label linkbase work.
- The lexical retriever stays the baseline. The roadmap called for dense-only
  first, which was the wrong order: a baseline should be the simplest system
  that works, and BM25 needs no model, no server and no network, so a full
  evaluation run costs seconds. Dense retrieval becomes the next delta row.
