"""Confidence intervals on the difference between two runs.

Section 9 of the technical documentation promises that deltas are reported as a
paired bootstrap interval rather than as two bare point estimates. This is that.

Why paired: both retrievers answer the same questions, so the comparison is
within-question. Treating the two runs as independent samples throws away that
pairing and gives an interval far wider than the evidence supports. What matters
is the questions where the two runs disagree.

Why bootstrap rather than a t-test: the per-question outcome is binary, the
sample is small, and resampling makes no assumption about the shape of the
difference. It is also easy to explain, which counts for something in a number
that goes in a README.

Resampling is seeded, so a reported interval can be reproduced exactly.
"""

from __future__ import annotations

import random
from statistics import mean

from pydantic import BaseModel

SEED = 20260729
RESAMPLES = 10_000


class Delta(BaseModel):
    """The difference between two runs on the same questions."""

    model_config = {"frozen": True}

    baseline: float
    candidate: float
    delta: float
    low: float
    high: float
    n: int
    discordant: int

    @property
    def significant(self) -> bool:
        """True when the interval excludes zero.

        Not a p-value and not a claim about truth: it says the sign of the
        difference survived resampling, which is the weakest honest statement
        that can be made about a delta this size.
        """
        return self.low > 0.0 or self.high < 0.0

    def render(self) -> str:
        marker = "" if self.significant else " (interval spans zero)"
        return (
            f"{self.baseline:.3f} -> {self.candidate:.3f}  "
            f"delta {self.delta:+.3f} [{self.low:+.3f}, {self.high:+.3f}]{marker}"
        )


def paired_bootstrap(
    baseline: list[float],
    candidate: list[float],
    resamples: int = RESAMPLES,
    confidence: float = 0.95,
) -> Delta:
    """Bootstrap a confidence interval on the mean per-question difference.

    ``baseline`` and ``candidate`` are per-question scores in the same order.
    """
    if len(baseline) != len(candidate):
        raise ValueError("paired comparison needs the same questions in the same order")
    if not baseline:
        raise ValueError("no questions to compare")

    differences = [c - b for b, c in zip(baseline, candidate, strict=True)]
    observed = mean(differences)

    rng = random.Random(SEED)
    size = len(differences)
    means: list[float] = []
    for _ in range(resamples):
        means.append(mean(rng.choices(differences, k=size)))
    means.sort()

    tail = (1.0 - confidence) / 2.0
    low = means[int(tail * resamples)]
    high = means[min(int((1.0 - tail) * resamples), resamples - 1)]

    return Delta(
        baseline=mean(baseline),
        candidate=mean(candidate),
        delta=observed,
        low=low,
        high=high,
        n=size,
        discordant=sum(1 for value in differences if value != 0.0),
    )
