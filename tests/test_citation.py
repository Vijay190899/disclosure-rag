"""Tests for narrowing a citation to the figure inside a passage.

Without this narrowing the citation metric collapses onto rank-1 recall and the
label plane's precision is unused. ADR-0011.
"""

from disclosure_rag.citation import looks_numeric


def test_figures_are_recognised_in_both_conventions() -> None:
    assert looks_numeric("5.996,4")
    assert looks_numeric("1,204.50")
    assert looks_numeric("192,9")
    assert looks_numeric("737.935")


def test_parenthesised_negatives_are_figures() -> None:
    assert looks_numeric("(1.204)")


def test_single_digits_are_not_worth_citing() -> None:
    """Note references and page numbers live here."""
    assert not looks_numeric("5")
    assert not looks_numeric("(1)")


def test_words_are_not_figures() -> None:
    assert not looks_numeric("Bilanzsumme")
    assert not looks_numeric("EUR")
    assert not looks_numeric("")


def test_a_year_counts_as_a_figure() -> None:
    """Deliberate: a year is a plausible answer and excluding it would bias scoring."""
    assert looks_numeric("2022")
