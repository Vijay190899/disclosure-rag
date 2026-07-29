# ADR-0006: The CI gate is deterministic, model-judged metrics run nightly

- **Status:** Accepted
- **Date:** 2026-07-29
- **Supersedes:** "CI fails if these regress" in the previous STACK.md, and "evaluation runs in CI as
  a regression gate" in the previous technical documentation

## Context

The previous documents stated in three places that Ragas metrics ran in CI as a regression gate.
That was not true. The workflow ran a linter and a test suite, Ragas was not even a dependency, and
there was no baseline file. The claim needed removing on accuracy grounds alone.

But the more useful question is whether it was a good idea, and it was not.

Ragas metrics such as faithfulness and answer relevance are computed by a language model judging
output. Putting them on the critical path means:

- **The build is nondeterministic.** The same commit can pass and then fail. A gate that fails for
  reasons unrelated to the diff is a gate developers learn to ignore, and an ignored gate is worse
  than no gate because it still costs time.
- **Every run costs money and wall-clock time**, on every push, including documentation-only ones.
- **The signal is weak at small n.** With a hundred questions, run-to-run variance in a
  model-judged score is comparable to the regression the gate is supposed to catch, so it produces
  false alarms and misses real drops.

There is a further problem specific to using a judge to score a system that also uses a model.
Language models systematically prefer their own outputs, and judge scores carry position and
verbosity bias. That does not make the metric useless, but it does mean it is a soft signal to
watch over time rather than a hard threshold to block on.

## Decision

**Two tiers, separated by whether the measurement is reproducible.**

**Tier 1, gates CI.** Deterministic metrics against fixed relevance judgements:

- recall@k and nDCG@10 against the qrels
- citation IoU@0.5 against the ledger's bounding boxes
- reconciliation precision and recall against ledger facts
- abstention precision and recall against the hand-labelled unanswerable stratum

These are pure functions of the index and the question set. Same input, same number, every time. No
model call, no cost, fast enough to run on every push. A drop below the recorded baseline fails the
build, and that failure always means something changed in the system.

**Tier 2, reported nightly and never gates.** Model-judged metrics: faithfulness, answer relevance.
Run on a schedule, recorded as a time series with variance across runs, and reviewed rather than
enforced. If a threshold is ever applied it will be to a confidence interval, not to a point
estimate.

**Latency and cost** are reported alongside both, because a retrieval improvement that triples p95
is a trade and not a win.

## When this arrives

Not yet. The gate joins CI at M2, when there is a harness and a baseline to gate on. Until then CI
runs lint, typecheck, hooks and tests, and the documentation says exactly that.

This is the specific mistake I am not repeating: the previous version described the finished state
of the pipeline as though it were the current state. The rule I am adopting is that a document
describes what runs today, and what is planned is labelled as planned with the milestone attached.

## Trade-offs I accept

- **Grounding regressions can reach main.** A drop in faithfulness that does not show up in
  retrieval or citation metrics will be caught the next night rather than at the gate. Acceptable:
  this is a solo project with no production traffic, and a nightly signal is enough.
- **Two systems instead of one.** The nightly job is extra surface to maintain.
- **Fixed qrels can go stale.** If the question set stops representing the corpus, the gate is
  measuring the wrong thing accurately. Mitigated by treating the question set as versioned data
  with its own review, not as a fixture that is written once and forgotten.

## A note on baselines

The baseline must be recorded before tuning starts, not after. Choosing what counts as success once
the results are visible is how evaluation tables become decoration. The ablation ladder in section 9
of the technical documentation is fixed in advance for the same reason: dense-only, then plus BM25,
then plus rerank, then plus span-preserving chunking, each with a delta row and a confidence
interval, whether or not the delta goes the way I expect.

If a component does not earn its row, it comes out of the stack. That includes the hybrid retrieval
decision I currently believe in most.

## Revisit if

- The question set grows enough that model-judged variance becomes small relative to the effect
  size, which would make a confidence-interval gate on tier 2 defensible.
- A deterministic grounding metric proves reliable enough to promote into tier 1, for example a
  small entailment model checking claims against cited spans, which would be a better gate than a
  general-purpose judge.
