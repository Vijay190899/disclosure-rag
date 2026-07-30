# ADR-0006: Evaluation is deterministic and runs without credentials

- **Status:** Accepted
- **Date:** 2026-07-30

## Context

The obvious way to evaluate a retrieval-augmented system is a model-judged suite: faithfulness,
answer relevance, and the rest. Putting that on the critical path has three costs.

- **The build becomes nondeterministic.** The same commit can pass and then fail. A gate that fails
  for reasons unrelated to the diff is a gate people learn to ignore, and an ignored gate is worse
  than none because it still costs time.
- **Every run costs money and wall-clock time**, on every push, including documentation-only ones.
- **The signal is weak at small n.** With a hundred questions, run-to-run variance in a model-judged
  score is comparable to the regression it is supposed to catch.

There is also a specific problem with judging a model's output using a model: language models
systematically prefer their own generations, and judge scores carry position and verbosity bias. That
does not make the metric useless, but it makes it a soft signal to watch rather than a threshold to
block on.

## Decision

**Everything reported is a deterministic function of the corpus and the question set.** No model call,
no credentials, no network. `make eval` reproduces every published number from a seed.

Two suites:

**Retrieval**, scored against bounding boxes taken from the filings' own tags: Recall@k, MRR@10,
nDCG@10, citation IoU. Standard names on purpose, so the numbers are comparable to anything else a
reader has seen.

**End to end**, scored on what a user receives: routing accuracy, answer exact match, abstention
precision and recall, false answer rate, and latency percentiles. Cases are generated from the ledgers
in three classes, so the suite needs no hand labelling:

- answerable figures, a concept and period the filer tagged
- unanswerable, another filing's concept that this one did not tag
- wrong-period traps, a real concept asked for a year it was not reported for, which separates knowing
  the concept from knowing the period

**Generation sits behind a protocol** with an extractive implementation as the default. For a question
whose answer is printed in the document, quoting the sentence and outlining it is correct, fully
attributable and cannot hallucinate. An LLM generator slots in for genuinely generative questions, and
its metrics would be reported separately and nightly rather than gating anything.

## Rules the suite follows

**Strata are never pooled.** The exact-figure stratum is the easy control, and averaging it with
harder cases would let good performance on lookups hide poor performance elsewhere, which is precisely
the failure this project exists to detect.

**A question with no result counts as a miss**, rather than being dropped. Otherwise a retriever could
improve its score by returning nothing.

**Deltas are reported as a paired bootstrap interval**, not two point estimates. Both retrievers answer
the same questions, so the comparison is within-question and the interval reflects that.

**Thresholds come from a curve, not from taste.** The abstention threshold is chosen from a published
sweep, and the sweep is in the README so the trade is visible rather than buried in a default.

**Metric definitions and the baseline are fixed before tuning.** Deciding what counts as success after
seeing results is how evaluation tables become decoration.

## Trade-offs accepted

- **Grounding quality is not gated.** A drop in faithfulness that does not show up in retrieval or
  citation metrics would not fail the build. Acceptable for a system with no production traffic, and
  the honest alternative is a gate nobody trusts.
- **Fixed question sets can go stale.** If the generated cases stop representing the corpus, the suite
  measures the wrong thing accurately. Mitigated by generating them from the ledgers rather than
  freezing them as a fixture.
