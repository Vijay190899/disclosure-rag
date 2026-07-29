"""Tests for the end-to-end answer pipeline."""

from decimal import Decimal

from disclosure_rag.answer.models import Route, Status
from disclosure_rag.answer.pipeline import AnswerPipeline, _format_figure
from disclosure_rag.ingest.chunker import Chunk
from disclosure_rag.labels.facts import Fact
from disclosure_rag.labels.ledger import FactLedger, LocatedFact
from disclosure_rag.provenance import Span
from disclosure_rag.retrieval.lexical import BM25Retriever

GOLD = Span(page=25, x0=0.63, y0=0.07, x1=0.66, y1=0.08)


def build() -> AnswerPipeline:
    fact = Fact(
        fact_id="f1",
        concept="ifrs-full:Assets",
        displayed="5.996,4",
        value=Decimal("5996400000"),
        unit="EUR",
        period="instant:2022-12-31",
    )
    ledger = FactLedger(
        document_id="doc",
        facts=[LocatedFact(fact=fact, span=GOLD)],
        concept_labels={"ifrs-full:Assets": "Bilanzsumme"},
    )
    chunks = [
        Chunk(
            chunk_id="c0",
            document_id="doc",
            text=(
                "Das Kreditportfolio der Gruppe unterliegt einem Ausfallrisiko, das laufend "
                "überwacht wird. Die Risikovorsorge wurde im Berichtsjahr erhöht."
            ),
            spans=[Span(page=100, x0=0.1, y0=0.2, x1=0.9, y1=0.3)],
            order=0,
        )
    ]
    retriever = BM25Retriever()
    retriever.index(chunks)
    return AnswerPipeline({"doc": ledger}, retriever)


def test_a_tagged_figure_is_answered_exactly_from_the_ledger() -> None:
    answer = build().answer("Wie hoch war Bilanzsumme zum 31.12.2022?", "doc")
    assert answer.status is Status.ANSWERED
    assert answer.route is Route.LEDGER
    assert answer.value == "5996400000"
    assert answer.confidence == 1.0


def test_a_ledger_citation_is_marked_exact_and_carries_the_tagged_span() -> None:
    """It is the filer's own tag location, not a prediction, and is labelled so."""
    answer = build().answer("Wie hoch war Bilanzsumme zum 31.12.2022?", "doc")
    citation = answer.citations[0]
    assert citation.exact is True
    assert citation.spans == [GOLD]
    assert citation.page == 25


def test_a_narrative_question_is_answered_from_passages() -> None:
    answer = build().answer("Welche Risiken bestehen beim Kreditportfolio?", "doc")
    assert answer.route is Route.PASSAGE
    assert answer.citations and answer.citations[0].exact is False


def test_an_unsupported_question_abstains_rather_than_guessing() -> None:
    answer = build().answer("Wie viele Mitarbeiter arbeiten in der Kantine?", "doc")
    assert answer.status is Status.ABSTAINED
    assert answer.reason


def test_abstention_still_returns_the_nearest_evidence() -> None:
    """Abstaining is more useful when the reader can see what was nearly matched."""
    pipeline = build()
    pipeline.abstain_below = 0.99
    answer = pipeline.answer("Welche Risiken bestehen beim Kreditportfolio?", "doc")
    assert answer.status is Status.ABSTAINED
    assert len(answer.citations) <= 1


def test_an_unknown_document_abstains() -> None:
    answer = build().answer("Wie hoch war Bilanzsumme zum 31.12.2022?", "absent")
    assert answer.status is Status.ABSTAINED
    assert answer.route is Route.NONE


def test_every_stage_is_timed() -> None:
    answer = build().answer("Wie hoch war Bilanzsumme zum 31.12.2022?", "doc")
    assert "route" in answer.timings_ms
    assert "ledger" in answer.timings_ms


def test_figures_are_rendered_in_the_corpus_convention() -> None:
    assert _format_figure(Decimal("5996400000"), "EUR") == "5.996.400.000,00 EUR"
    assert _format_figure(Decimal("-1204"), "EUR") == "-1.204,00 EUR"
    assert _format_figure(Decimal("1204.5"), "") == "1.204,50"
    # Always two places: 192.900.000,0 invites a misread of the last digit.
    assert _format_figure(Decimal("192900000.0"), "EUR") == "192.900.000,00 EUR"
