# ADR-0011: Cite the number, not the block

- **Status:** Accepted
- **Date:** 2026-07-30
- **Amends:** the metric definitions in [ADR-0009](0009-m2-baseline-findings.md) and section 9 of the
  technical documentation

## Context

An adversarial review of this project read the source rather than the write-up and found that the
central metric carried no information.

I had noted in `metrics.py` that `citation_coverage@1` and `recall@1` were identical by construction:
both ask whether the top-ranked result contains the gold region. I recorded it as a curiosity and
moved on. What I failed to see is the consequence.

**Citations were block-level. A gold fact is a number.** A tagged figure occupies about 0.00026 of a
page; the text block containing it occupies about 0.0175, roughly seventy times more. At that
granularity, "does the citation contain the gold box" is answered by any block on the right part of
the page. So:

- The citation metric collapsed onto rank-1 recall and told me nothing beyond it.
- **Page-level gold would have scored identically.** Nothing in the harness could tell the difference
  between a bounding box accurate to a number and a box the size of a page.
- The label plane's whole output, 865 located facts at a median IoU of 0.947, was bought and never
  spent.

That is worse than the poor retrieval numbers. The project's stated differentiator, that standard
evaluation cannot see whether a citation points at the right place, was **also true of my own
evaluation**.

## Decision

**Narrow the citation from the retrieved block to the figure inside it**, and score that against the
tagged figure with intersection over union.

`citation.py` does the narrowing. Word boxes are read from the rendered PDF at citation time rather
than stored on every chunk, since word-level geometry would multiply the index for something needed
only on passages actually cited. Within the retrieved chunk it finds the line sharing the most terms
with the query and returns the numeric tokens on that line.

The rule is deliberately deterministic rather than a model. A financial statement row puts its label
and its values on one line, which the M2 run confirmed on real documents, so a line is the structure
the format actually offers.

**IoU becomes the right metric at this granularity.** Predicted and gold are both number-sized, so
overlap measures the quality of the citation rather than the difference in scale between a number and
a paragraph. ADR-0009 was right to reject IoU for block-level citations and right to use containment
there; both remain reported. The mistake was stopping at block level.

## Result

Same corpus, same 120 questions, BM25, after this change and the three measurement fixes committed
alongside it (corpus-native German dates in queries, seeded question sampling, a real-tokenizer
window guard).

| chunk tokens | recall@1 | recall@5 | recall@10 | shown first when found |
|---|---|---|---|---|
| 300 | 0.308 | 0.542 | 0.633 | 0.487 |
| 600 | **0.350** | **0.567** | **0.692** | 0.506 |

Recall@1 rose from 0.208 to 0.350, almost entirely from removing the ISO-date tokens that were
poisoning every query.

### The citation number, and how many figures you are allowed to outline

`max_spans` controls how many figures a citation highlights. It looked like a tuning knob and it is
not: it is the difference between what a reader gets and an upper bound.

| figures outlined | citation IoU@0.5 | mean citation IoU |
|---|---|---|
| **1, which is what a reader gets** | **0.058** | 0.056 |
| 2 | 0.192 | 0.181 |
| 3 | 0.225 | 0.214 |

I had written up 0.225 before noticing that it scores the best of three candidates against gold. A
product outlines one region. **The honest figure is 0.058.**

## The result

**Retrieval puts the right passage in the top ten for 69% of questions. Asked to outline the single
figure that answers the question, it is correct 5.8% of the time.**

That is the finding, and it is far larger than I expected when I started measuring. No answer-level
metric sees it, and no passage-level metric sees it either: recall@10 of 0.692 and citation IoU of
0.058 describe the same run.

The mechanism is now legible rather than inferred. A statement row carries several periods' values on
one line. The line-based selector finds the right row and then cannot choose among its numbers,
because the information that distinguishes them, the column header, is not on the line. So it is
right about the row and wrong about the cell, almost every time.

This is the same constraint diagnosed in ADR-0010 from the retrieval side, now visible in the citation
metric where it belongs. It is not a tuning problem and a better retriever will not move it: knowing
which passage is relevant is a different problem from knowing which cell in it answers the question.

It also makes the next rung a prediction rather than a hope. Header propagation carries the column
header into the chunk, which is exactly the missing information, so it should move 0.058 and should
leave recall roughly alone. If it moves recall instead, my explanation is wrong.

## Consequences

- `recall@1` and `citation_coverage@1` remain identical and both remain reported, now clearly labelled
  as the block-level pair, with `citation_iou_at_50` as the figure-level metric.
- The label plane's precision is load-bearing for the first time.
- The demo follows directly: the region to outline for a reader is a number, and `/page` renders it.
- Mean citation IoU of 0.230 rather than something near 1.0 for the cases it gets right indicates the
  selected token is often adjacent to the tagged one, which is the multi-period column problem
  showing up in the metric instead of hiding in it.

## What this does not fix

`select_numeric_spans` cannot choose between periods on a row carrying several, because the column
header that distinguishes them is not on the line. It returns the candidates rather than guessing, so
the ambiguity stays visible in the score. That is the open finding, and the next rung, header
propagation, is aimed squarely at it.
