"""Tests for the verified example questions.

The point of this module is that an example is proven before it is offered, so
the tests are about what gets rejected rather than what gets produced.
"""

from decimal import Decimal

from disclosure_rag.answer.models import Answer, Citation, Route, Status
from disclosure_rag.examples import candidates, working_examples
from disclosure_rag.labels.facts import Fact
from disclosure_rag.labels.ledger import FactLedger, LocatedFact
from disclosure_rag.provenance import Span

SPAN = Span(page=3, x0=0.1, y0=0.1, x1=0.2, y1=0.2)


def fact(fact_id: str, concept: str, value: str, period: str) -> LocatedFact:
    return LocatedFact(
        fact=Fact(
            fact_id=fact_id,
            concept=concept,
            displayed=value,
            value=Decimal(value),
            unit="EUR",
            period=period,
        ),
        span=SPAN,
    )


def ledger_with(*rows: LocatedFact, labels: dict[str, str] | None = None) -> FactLedger:
    return FactLedger(
        document_id="doc",
        facts=list(rows),
        concept_labels=labels
        or {"ifrs-full:Assets": "Bilanzsumme", "ifrs-full:Revenue": "Umsatzerlöse"},
    )


def answered(question: str) -> Answer:
    return Answer(
        question=question,
        status=Status.ANSWERED,
        route=Route.LEDGER,
        text="1",
        citations=[Citation(document_id="doc", page=3, spans=[SPAN], exact=True)],
    )


def test_a_candidate_reads_the_way_the_benchmark_asks() -> None:
    ledger = ledger_with(fact("f1", "ifrs-full:Assets", "1", "instant:2022-12-31"))
    assert candidates(ledger) == ["Wie hoch war Bilanzsumme zum 31.12.2022?"]


def test_concepts_without_a_declared_label_are_not_offered() -> None:
    """Asking with a raw concept name is not a question a person would type."""
    ledger = ledger_with(
        fact("f1", "custom:Unlabelled", "1", "instant:2022-12-31"),
        labels={"ifrs-full:Assets": "Bilanzsumme"},
    )
    assert candidates(ledger) == []


def test_an_ambiguous_concept_is_never_offered_as_an_example() -> None:
    """Two values for one concept and period is what the system abstains on.

    Offering one as an example would advertise the abstention path as if it
    were the product.
    """
    ledger = ledger_with(
        fact("f1", "ifrs-full:Assets", "1", "instant:2022-12-31"),
        fact("f2", "ifrs-full:Assets", "2", "instant:2022-12-31"),
    )
    assert candidates(ledger) == []


def test_the_order_is_stable_across_runs() -> None:
    ledger = ledger_with(
        fact("f1", "ifrs-full:Assets", "1", "instant:2022-12-31"),
        fact("f2", "ifrs-full:Revenue", "2", "2022-01-01/2022-12-31"),
    )
    assert candidates(ledger) == candidates(ledger)


def test_only_questions_that_answer_exactly_survive() -> None:
    ledger = ledger_with(
        fact("f1", "ifrs-full:Assets", "1", "instant:2022-12-31"),
        fact("f2", "ifrs-full:Revenue", "2", "2022-01-01/2022-12-31"),
    )
    asked: list[str] = []

    def ask(question: str) -> Answer:
        asked.append(question)
        if "Bilanzsumme" in question:
            return answered(question)
        return Answer(question=question, status=Status.ABSTAINED, route=Route.NONE)

    kept = working_examples(ledger, ask)
    assert kept == ["Wie hoch war Bilanzsumme zum 31.12.2022?"]
    assert len(asked) == 2


def test_an_answer_without_an_exact_citation_is_not_an_example() -> None:
    """A retrieved passage is a legitimate answer and a poor demonstration of
    the thing this system is for."""
    ledger = ledger_with(fact("f1", "ifrs-full:Assets", "1", "instant:2022-12-31"))
    predicted = Answer(
        question="q",
        status=Status.ANSWERED,
        route=Route.PASSAGE,
        citations=[Citation(document_id="doc", page=3, spans=[SPAN], exact=False)],
    )
    assert working_examples(ledger, lambda _question: predicted) == []


def test_it_stops_asking_once_it_has_enough() -> None:
    rows = [
        fact(f"f{index}", f"ifrs-full:C{index}", str(index), "instant:2022-12-31")
        for index in range(10)
    ]
    ledger = ledger_with(*rows, labels={f"ifrs-full:C{index}": f"L{index}" for index in range(10)})
    asked: list[str] = []

    def ask(question: str) -> Answer:
        asked.append(question)
        return answered(question)

    assert len(working_examples(ledger, ask, limit=3)) == 3
    assert len(asked) == 3
