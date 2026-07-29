"""Tests for the provenance contract."""

import pytest
from pydantic import ValidationError

from disclosure_rag.provenance import Span, best_iou, union_on_page


def span(page: int = 0, x0: float = 0.1, y0: float = 0.1, x1: float = 0.2, y1: float = 0.2) -> Span:
    return Span(page=page, x0=x0, y0=y0, x1=x1, y1=y1)


def test_identical_spans_have_iou_one() -> None:
    assert span().iou(span()) == pytest.approx(1.0)


def test_disjoint_spans_have_iou_zero() -> None:
    assert span(x0=0.1, x1=0.2).iou(span(x0=0.5, x1=0.6)) == 0.0


def test_half_overlap() -> None:
    a = Span(page=0, x0=0.0, y0=0.0, x1=0.2, y1=0.1)
    b = Span(page=0, x0=0.1, y0=0.0, x1=0.3, y1=0.1)
    # Intersection is half of each, so union is 1.5 boxes: 0.5 / 1.5.
    assert a.iou(b) == pytest.approx(1 / 3)


def test_same_box_on_a_different_page_scores_zero() -> None:
    """A correct-looking box on the wrong page is wrong, not partially right.

    Scoring it as a near miss would hide the exact failure this project exists
    to detect, so the page check comes before any geometry.
    """
    assert span(page=3).iou(span(page=4)) == 0.0


def test_from_rect_normalises_against_page_size() -> None:
    result = Span.from_rect(2, 100, 50, 200, 100, width=1000, height=500)
    assert (result.page, result.x0, result.y0, result.x1, result.y1) == (2, 0.1, 0.1, 0.2, 0.2)


def test_from_rect_rejects_a_zero_sized_page() -> None:
    with pytest.raises(ValueError, match="positive"):
        Span.from_rect(0, 0, 0, 1, 1, width=0, height=100)


def test_inverted_corners_are_rejected_at_construction() -> None:
    with pytest.raises(ValidationError):
        Span(page=0, x0=0.8, y0=0.1, x1=0.2, y1=0.2)


def test_coordinates_outside_the_page_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Span(page=0, x0=0.1, y0=0.1, x1=1.4, y1=0.2)


def test_best_iou_picks_the_closest_gold_span() -> None:
    predicted = Span(page=0, x0=0.0, y0=0.0, x1=0.2, y1=0.1)
    gold = [span(page=1), Span(page=0, x0=0.0, y0=0.0, x1=0.2, y1=0.1)]
    assert best_iou(predicted, gold) == pytest.approx(1.0)


def test_best_iou_of_nothing_is_zero() -> None:
    assert best_iou(span(), []) == 0.0


def test_union_covers_every_span_on_the_page() -> None:
    result = union_on_page(
        [
            Span(page=1, x0=0.1, y0=0.1, x1=0.2, y1=0.2),
            Span(page=1, x0=0.15, y0=0.05, x1=0.4, y1=0.3),
        ]
    )
    assert result == Span(page=1, x0=0.1, y0=0.05, x1=0.4, y1=0.3)


def test_union_across_pages_is_an_error() -> None:
    """The caller has to decide what a cross-page highlight means, not this."""
    with pytest.raises(ValueError, match="across pages"):
        union_on_page([span(page=1), span(page=2)])
