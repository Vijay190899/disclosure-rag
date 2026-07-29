"""Tests for drawing cited regions onto a page."""

import pytest

from disclosure_rag.render import parse_regions


def test_a_single_region_parses() -> None:
    spans = parse_regions("0.1,0.2,0.3,0.4", page=7)
    assert len(spans) == 1
    assert (spans[0].page, spans[0].x0, spans[0].y1) == (7, 0.1, 0.4)


def test_several_regions_parse() -> None:
    """A citation can cover more than one region, so the wire format must too."""
    assert len(parse_regions("0.1,0.1,0.2,0.2;0.3,0.3,0.4,0.4", page=0)) == 2


def test_blank_input_yields_no_regions() -> None:
    assert parse_regions("", page=0) == []
    assert parse_regions("  ;  ", page=0) == []


def test_the_wrong_number_of_values_is_rejected() -> None:
    with pytest.raises(ValueError, match="x0,y0,x1,y1"):
        parse_regions("0.1,0.2,0.3", page=0)


def test_non_numeric_values_are_rejected() -> None:
    with pytest.raises(ValueError, match="numbers"):
        parse_regions("a,b,c,d", page=0)


def test_out_of_range_values_are_rejected() -> None:
    """Coordinates are page fractions, so anything above 1 is a caller error."""
    with pytest.raises(Exception):  # noqa: B017 - pydantic validation
        parse_regions("0.1,0.2,1.4,0.4", page=0)
