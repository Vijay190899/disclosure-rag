"""Tests for routing a question to the structured or the passage path."""

from disclosure_rag.answer.models import Route
from disclosure_rag.answer.router import ConceptIndex, route_question

INDEX = ConceptIndex(
    labels={
        "ifrs-full:Assets": ("Bilanzsumme",),
        "ifrs-full:Revenue": ("Umsatzerlöse",),
        "ifrs-full:InterestExpense": ("Summe Zinsaufwendungen",),
        "x:Summe": ("Summe",),
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


def test_a_pooled_wording_reaches_a_concept_the_filer_did_not_label() -> None:
    """One issuer's wording, another issuer's untagged concept.

    This is the case the corpus actually contains: a filing that references the
    official taxonomy rather than bundling labels has no wording of its own, so
    without pooling its tagged figures are unreachable.
    """
    index = ConceptIndex(
        labels={"ifrs-full:Assets": ("Bilanzsumme", "Summe Aktiva")},
        periods={"ifrs-full:Assets": {"instant:2022-12-31"}},
    )
    decision = route_question("Wie hoch war Summe Aktiva zum 31.12.2022?", index)
    assert decision.route is Route.LEDGER
    assert decision.concept == "ifrs-full:Assets"


def test_two_wordings_for_one_concept_are_not_ambiguity() -> None:
    """Ambiguity means two concepts, not two names for one.

    Scoring each wording separately would list the same concept twice and
    abstain on a question that identifies exactly one figure.
    """
    index = ConceptIndex(
        labels={"ifrs-full:Assets": ("Bilanzsumme", "Bilanzsumme gesamt")},
        periods={"ifrs-full:Assets": {"instant:2022-12-31"}},
    )
    decision = route_question("Wie hoch war Bilanzsumme gesamt zum 31.12.2022?", index)
    assert decision.route is Route.LEDGER
    assert decision.concept == "ifrs-full:Assets"


def test_a_pooled_label_cannot_invent_a_period() -> None:
    """Borrowing a wording must not borrow a filing's reporting periods."""
    index = ConceptIndex(
        labels={"ifrs-full:Assets": ("Bilanzsumme",)},
        periods={"ifrs-full:Assets": {"instant:2022-12-31"}},
    )
    decision = route_question("Wie hoch war Bilanzsumme zum 31.12.2019?", index)
    assert decision.route is Route.PASSAGE
    assert "not tagged" in decision.reason


def test_a_label_shared_by_two_concepts_is_still_ambiguous() -> None:
    index = ConceptIndex(
        labels={
            "ifrs-full:Inventories": ("Vorräte",),
            "ifrs-full:AdjustmentsForInventories": ("Vorräte",),
        },
        periods={
            "ifrs-full:Inventories": {"instant:2022-12-31"},
            "ifrs-full:AdjustmentsForInventories": {"instant:2022-12-31"},
        },
    )
    decision = route_question("Wie hoch war Vorräte zum 31.12.2022?", index)
    assert decision.concept == ""
    assert len(decision.concepts) == 2


def test_a_question_that_names_more_than_the_label_does_not_route() -> None:
    """The failure this guards: "Erwerb von Sachanlagen" asks about a cash
    flow and contains the label "Sachanlagen", so containment alone returns the
    balance sheet carrying amount with full confidence and an exact citation.
    """
    index = ConceptIndex(
        labels={"ifrs-full:PropertyPlantAndEquipment": ("Sachanlagen",)},
        periods={"ifrs-full:PropertyPlantAndEquipment": {"instant:2022-12-31"}},
    )
    decision = route_question("Wie hoch war Erwerb von Sachanlagen zum 31.12.2022?", index)
    assert decision.route is Route.PASSAGE
    assert "names more than" in decision.reason


def test_period_framing_is_not_something_the_question_names() -> None:
    """ "im Geschäftsjahr 2022" says which year, not which figure."""
    index = ConceptIndex(
        labels={"ifrs-full:Revenue": ("Umsatzerlöse",)},
        periods={"ifrs-full:Revenue": {"2022-01-01/2022-12-31"}},
    )
    decision = route_question("Wie hoch war Umsatzerlöse im Geschäftsjahr 2022?", index)
    assert decision.route is Route.LEDGER


def test_a_qualifier_the_filing_does_not_tag_falls_back_rather_than_guessing() -> None:
    """Falling back to retrieval is the designed degradation. Answering with the
    group figure because the question said "des Konzerns" would not be.
    """
    index = ConceptIndex(
        labels={"ifrs-full:Revenue": ("Umsatzerlöse",)},
        periods={"ifrs-full:Revenue": {"2022-01-01/2022-12-31"}},
    )
    decision = route_question(
        "Wie hoch waren die Umsatzerlöse des Segments Karton im Geschäftsjahr 2022?", index
    )
    assert decision.route is Route.PASSAGE
