"""Tests for the paired bootstrap.

This function produces the confidence intervals in the README and in ADR-0005,
including the one the retrieval decision now rests on. An untested statistic
that appears in a published table is a claim nobody has checked, so these test
the properties the interval has to have rather than the digits it happens to
emit.
"""

import pytest

from disclosure_rag.evaluation.stats import paired_bootstrap


def test_identical_runs_have_a_zero_delta_and_an_interval_of_zero_width() -> None:
    """Every resample of a list of zeroes is zero. Anything else would mean the
    resampling itself was inventing variation."""
    scores = [1.0, 0.0, 1.0, 1.0, 0.0]
    delta = paired_bootstrap(scores, scores)
    assert delta.delta == 0.0
    assert (delta.low, delta.high) == (0.0, 0.0)
    assert delta.discordant == 0
    assert not delta.significant


def test_the_point_estimate_is_the_mean_per_question_difference() -> None:
    baseline = [1.0, 1.0, 0.0, 0.0]
    candidate = [1.0, 0.0, 1.0, 1.0]
    delta = paired_bootstrap(baseline, candidate)
    assert delta.baseline == 0.5
    assert delta.candidate == 0.75
    assert delta.delta == pytest.approx(0.25)


def test_the_interval_brackets_the_point_estimate() -> None:
    baseline = [1.0] * 30 + [0.0] * 70
    candidate = [1.0] * 55 + [0.0] * 45
    delta = paired_bootstrap(baseline, candidate)
    assert delta.low <= delta.delta <= delta.high


def test_a_large_consistent_difference_excludes_zero() -> None:
    delta = paired_bootstrap([0.0] * 100, [1.0] * 100)
    assert delta.delta == 1.0
    assert delta.significant


def test_a_small_difference_on_few_questions_does_not() -> None:
    """The narrative stratum's actual situation, reproduced.

    Twenty questions, the candidate winning five and losing two, so a delta of
    +0.150 over seven disagreements. That is the dense-to-hybrid comparison in
    ADR-0005, and it must come back inconclusive. If this ever reported
    significance the README would be overclaiming, which is the specific mistake
    this project exists to avoid.
    """
    baseline = [0.0] * 5 + [1.0] * 2 + [0.0] * 13
    candidate = [1.0] * 5 + [0.0] * 2 + [0.0] * 13
    delta = paired_bootstrap(baseline, candidate)
    assert delta.delta == pytest.approx(0.15)
    assert delta.discordant == 7
    assert not delta.significant
    assert delta.low < 0.0 < delta.high


def test_an_interval_that_only_touches_zero_is_not_significant() -> None:
    """When every disagreement points the same way the lower bound lands on
    zero exactly. ``significant`` is ``low > 0``, not ``low >= 0``, so this is
    reported as inconclusive rather than as a win."""
    delta = paired_bootstrap([1.0] * 4 + [0.0] * 16, [1.0] * 7 + [0.0] * 13)
    assert delta.low == 0.0
    assert not delta.significant


def test_pairing_is_by_position_so_order_carries_meaning() -> None:
    """Same totals, different per-question pairing, different discordance.

    A comparison that ignored the pairing would call these identical, and would
    report an interval far wider than the evidence supports.
    """
    aligned = paired_bootstrap([1.0, 0.0], [1.0, 0.0])
    opposed = paired_bootstrap([1.0, 0.0], [0.0, 1.0])
    assert aligned.discordant == 0
    assert opposed.discordant == 2
    assert aligned.delta == opposed.delta == 0.0


def test_reversing_the_arguments_reverses_the_sign() -> None:
    forward = paired_bootstrap([0.0, 0.0, 1.0], [1.0, 1.0, 1.0])
    backward = paired_bootstrap([1.0, 1.0, 1.0], [0.0, 0.0, 1.0])
    assert forward.delta == pytest.approx(-backward.delta)
    assert forward.low == pytest.approx(-backward.high)
    assert forward.high == pytest.approx(-backward.low)


def test_the_same_input_gives_the_same_interval_every_time() -> None:
    """Seeded, because a published interval that moves between runs cannot be
    reproduced by anyone reading the README."""
    baseline = [1.0, 0.0] * 40
    candidate = [1.0, 1.0] * 40
    first = paired_bootstrap(baseline, candidate)
    second = paired_bootstrap(baseline, candidate)
    assert (first.low, first.high) == (second.low, second.high)


def test_a_wider_confidence_level_gives_a_wider_interval() -> None:
    baseline = [1.0] * 20 + [0.0] * 30
    candidate = [1.0] * 30 + [0.0] * 20
    narrow = paired_bootstrap(baseline, candidate, confidence=0.80)
    wide = paired_bootstrap(baseline, candidate, confidence=0.99)
    assert wide.low <= narrow.low
    assert wide.high >= narrow.high


def test_mismatched_lengths_are_rejected_rather_than_truncated() -> None:
    """Silently zipping to the shorter list would compare different questions
    and report a confident number about nothing."""
    with pytest.raises(ValueError, match="same questions"):
        paired_bootstrap([1.0, 0.0], [1.0])


def test_an_empty_comparison_is_rejected() -> None:
    with pytest.raises(ValueError, match="no questions"):
        paired_bootstrap([], [])


def test_render_marks_an_interval_that_spans_zero() -> None:
    """The marker is what stops a reader taking a point estimate as a result."""
    inconclusive = paired_bootstrap([1.0, 0.0, 1.0, 0.0], [0.0, 1.0, 1.0, 0.0]).render()
    assert "spans zero" in inconclusive
    assert "spans zero" not in paired_bootstrap([0.0] * 50, [1.0] * 50).render()
