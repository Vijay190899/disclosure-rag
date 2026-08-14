"""Tests for confidence calibration.

The point of the module under test is to stop a score being passed off as a
probability, so these check that it says so when it is not.
"""

from __future__ import annotations

import pytest

from disclosure_rag.evaluation.calibration import calibrate, render_calibration


def test_a_perfectly_calibrated_system_has_no_error() -> None:
    """Says 0.9, right 9 times in 10; says 0.1, right 1 time in 10."""
    predictions = [(0.9, True)] * 9 + [(0.9, False)]
    predictions += [(0.1, True)] + [(0.1, False)] * 9
    result = calibrate(predictions)
    assert result.expected_calibration_error == pytest.approx(0.0, abs=0.01)


def test_confident_and_wrong_is_reported_as_over_confidence() -> None:
    """The direction that costs trust, because a reader would not check."""
    result = calibrate([(0.95, False)] * 20)
    assert result.expected_calibration_error == pytest.approx(0.95, abs=0.01)
    assert result.overconfidence == pytest.approx(0.95, abs=0.01)


def test_diffident_and_right_is_error_but_not_over_confidence() -> None:
    """Under-confidence is a waste, not a hazard, and is counted separately."""
    result = calibrate([(0.1, True)] * 20)
    assert result.expected_calibration_error == pytest.approx(0.9, abs=0.01)
    assert result.overconfidence == pytest.approx(0.0, abs=0.01)


def test_one_bad_band_is_visible_even_when_the_average_is_good() -> None:
    """A single ECE hides shape, which is why the worst bin is reported too.

    One confidently wrong answer among ninety-nine right ones barely moves the
    average, and is exactly the case a reader would be burned by.
    """
    result = calibrate([(0.95, True)] * 99 + [(0.85, False)])
    assert result.expected_calibration_error < 0.1
    assert result.max_calibration_error > 0.5
    assert result.max_calibration_error > result.expected_calibration_error * 5


def test_confidence_of_one_lands_in_the_top_band() -> None:
    """The upper edge is inclusive there, or perfect confidence would be dropped."""
    result = calibrate([(1.0, True)] * 5)
    assert result.samples == 5
    assert result.bins[-1].count == 5


def test_empty_bands_are_dropped_rather_than_scored_as_perfect() -> None:
    result = calibrate([(0.95, True)] * 10)
    assert len(result.bins) == 1


def test_no_predictions_yields_an_empty_result() -> None:
    result = calibrate([])
    assert result.samples == 0
    assert result.bins == []
    assert "no predictions" in render_calibration(result)


def test_the_table_shows_the_gap_with_its_sign() -> None:
    rendered = render_calibration(calibrate([(0.95, False)] * 10))
    assert "+0.950" in rendered or "+0.9" in rendered
