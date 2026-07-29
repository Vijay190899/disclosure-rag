"""Tests for fact extraction and number normalisation.

The normalisation cases are the important ones. An error there rescales every
label by a factor of a thousand without failing anything, and an earlier version
of this code had exactly that bug: it read the Austrian and German "1.204" as
1.204 rather than 1204.
"""

from decimal import Decimal
from pathlib import Path

import pytest
from lxml import etree

from disclosure_rag.labels.facts import PROBE_URI, LxmlFactSource, normalise_number

FIXTURE = Path(__file__).parent / "fixtures" / "mini_filing.xhtml"


@pytest.mark.parametrize(
    ("text", "fmt", "expected"),
    [
        # A lone separator group is ambiguous, and three trailing digits mean
        # grouping under either convention.
        ("1,204", "", "1204"),
        ("1.204", "", "1204"),
        ("12.345.678", "", "12345678"),
        # Both separators present: the later one is the decimal point.
        ("1.204,50", "", "1204.50"),
        ("1,204.50", "", "1204.50"),
        # Not three trailing digits, so it is a decimal.
        ("0,5", "", "0.5"),
        ("1,25", "", "1.25"),
        # The format attribute settles it outright and overrides the heuristic.
        ("1.204", "ixt:num-comma-decimal", "1204"),
        ("1.204", "ixt:num-dot-decimal", "1.204"),
        ("1,5", "ixt:num-comma-decimal", "1.5"),
        # Negatives, in both conventions used by filers.
        ("(1,204)", "", "-1204"),
        ("-1.204", "", "-1204"),
        # Surrounding text is stripped.
        ("EUR 1,204 Mio", "", "1204"),
        # Nothing usable.
        ("", "", None),
        ("n/a", "", None),
        ("-", "", None),
    ],
)
def test_normalise_number(text: str, fmt: str, expected: str | None) -> None:
    result = normalise_number(text, fmt)
    assert result == (Decimal(expected) if expected is not None else None)


def test_extraction_finds_every_tagged_fact() -> None:
    facts = LxmlFactSource().extract(FIXTURE)
    assert len(facts) == 5
    assert {fact.concept for fact in facts} == {
        "ifrs-full:Revenue",
        "ifrs-full:CostOfSales",
        "ifrs-full:Assets",
    }


def test_scale_is_applied() -> None:
    facts = {(f.concept, f.period): f for f in LxmlFactSource().extract(FIXTURE)}
    revenue = facts[("ifrs-full:Revenue", "2022-01-01/2022-12-31")]
    # Displayed 1.204 with scale 3: Austrian grouping, so 1204 thousand.
    assert revenue.displayed == "1.204"
    assert revenue.value == Decimal("1204000")


def test_the_format_attribute_drives_a_decimal_comma() -> None:
    facts = {f.concept: f for f in LxmlFactSource().extract(FIXTURE)}
    assets = facts["ifrs-full:Assets"]
    # 5.996,4 declared as comma-decimal, scale 6.
    assert assets.value == Decimal("5996400000.0")


def test_negative_sign_is_applied() -> None:
    costs = [f for f in LxmlFactSource().extract(FIXTURE) if f.concept == "ifrs-full:CostOfSales"]
    assert all(fact.value < 0 for fact in costs)


def test_prior_year_comparatives_keep_their_own_period() -> None:
    """Ignoring contextRef would silently score last year's figure as this year's."""
    revenue = [f for f in LxmlFactSource().extract(FIXTURE) if f.concept == "ifrs-full:Revenue"]
    periods = {fact.period for fact in revenue}
    assert periods == {"2022-01-01/2022-12-31", "2021-01-01/2021-12-31"}


def test_instant_contexts_are_resolved() -> None:
    facts = {f.concept: f for f in LxmlFactSource().extract(FIXTURE)}
    assert facts["ifrs-full:Assets"].period == "instant:2022-12-31"


def test_stamping_wraps_each_fact_in_an_anchor(tmp_path: Path) -> None:
    stamped = tmp_path / "stamped.xhtml"
    facts = LxmlFactSource().extract(FIXTURE, stamped_out=stamped)

    tree = etree.parse(str(stamped), etree.XMLParser(recover=True))
    hrefs = {
        element.get("href")
        for element in tree.iter("{http://www.w3.org/1999/xhtml}a")
        if (element.get("href") or "").startswith(PROBE_URI)
    }
    assert hrefs == {f"{PROBE_URI}/{fact.fact_id}" for fact in facts}


def test_stamping_preserves_the_text_around_a_fact(tmp_path: Path) -> None:
    """Moving an element into an anchor must carry its tail, or text is lost."""
    stamped = tmp_path / "stamped.xhtml"
    LxmlFactSource().extract(FIXTURE, stamped_out=stamped)
    root = etree.parse(str(stamped), etree.XMLParser(recover=True)).getroot()
    text = " ".join(str(piece) for piece in root.itertext())
    assert "Die Gesamtaktiva der Gruppe beliefen sich" in " ".join(text.split())
    # The closing bracket after a negative figure is tail text on the element.
    assert "870" in text


def test_extraction_without_an_output_path_does_not_write(tmp_path: Path) -> None:
    LxmlFactSource().extract(FIXTURE)
    assert not list(tmp_path.iterdir())


def test_unit_refs_resolve_to_their_measure() -> None:
    """A fact must report EUR, not the document-local id "u-1"."""
    facts = LxmlFactSource().extract(FIXTURE)
    assert {fact.unit for fact in facts} == {"EUR"}
