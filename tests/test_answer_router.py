"""Tests for routing a question to the structured or the passage path."""

from disclosure_rag.answer.models import Route
from disclosure_rag.answer.router import ConceptIndex, route_question

INDEX = ConceptIndex(
    labels={
        "ifrs-full:Assets": "Bilanzsumme",
        "ifrs-full:Revenue": "Umsatzerlöse",
        "ifrs-full:InterestExpense": "Summe Zinsaufwendungen",
        "x:Summe": "Summe",
    },
    periods={
        "ifrs-full:Assets": {"instant:2022-12-31", "instant:2021-12-31"},
        "ifrs-full:Revenue": {"2022-01-01/2022-12-31"},
        "ifrs-full:InterestExpense": {"2022-01-01/2022-12-31"},
        "x:Summe": {"instant:2022-12-31"},
    },
)


def test_a_tagged_concept_with_a_date_routes_to_the_ledger() -> None:
    decision = route_question("Wie hoch war Bilanzsumme zum 31.12.2022?", INDEX)
    assert decision.route is Route.LEDGER
    assert decision.concept == "ifrs-full:Assets"
    assert decision.period == "instant:2022-12-31"


def test_a_bare_year_resolves_a_duration_period() -> None:
    decision = route_question("Wie hoch war Umsatzerlöse im Geschäftsjahr 2022?", INDEX)
    assert decision.route is Route.LEDGER
    assert decision.period == "2022-01-01/2022-12-31"


def test_the_right_year_is_chosen_when_several_are_tagged() -> None:
    decision = route_question("Bilanzsumme zum 31.12.2021", INDEX)
    assert decision.period == "instant:2021-12-31"


def test_a_concept_without_a_period_goes_to_passages() -> None:
    """A figure without a year is ambiguous across years, so do not guess."""
    decision = route_question("Wie hoch war Bilanzsumme?", INDEX)
    assert decision.route is Route.PASSAGE
    assert "no period" in decision.reason


def test_a_period_the_concept_was_not_tagged_for_goes_to_passages() -> None:
    decision = route_question("Wie hoch war Umsatzerlöse im Geschäftsjahr 2019?", INDEX)
    assert decision.route is Route.PASSAGE
    assert "not tagged" in decision.reason


def test_a_qualitative_question_goes_to_passages() -> None:
    decision = route_question(
        "Welche Risiken bestehen im Zusammenhang mit dem Kreditportfolio?", INDEX
    )
    assert decision.route is Route.PASSAGE
    assert "no tagged concept" in decision.reason


def test_the_longest_matching_label_wins() -> None:
    """ "Summe Zinsaufwendungen" must beat the bare label "Summe"."""
    decision = route_question("Summe Zinsaufwendungen im Geschäftsjahr 2022", INDEX)
    assert decision.concept == "ifrs-full:InterestExpense"


def test_a_partial_label_match_is_not_enough() -> None:
    """Sharing one word with a multi-word label is not naming the concept."""
    decision = route_question("Wie hoch war die Summe der Aufwendungen 2022?", INDEX)
    assert decision.concept != "ifrs-full:InterestExpense"


def test_an_empty_question_goes_to_passages() -> None:
    assert route_question("", INDEX).route is Route.PASSAGE


def test_an_empty_index_never_routes_to_the_ledger() -> None:
    decision = route_question("Bilanzsumme zum 31.12.2022", ConceptIndex())
    assert decision.route is Route.PASSAGE
