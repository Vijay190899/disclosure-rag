"""Tests for the end-to-end scorer.

Every number in the README's headline table comes out of ``Benchmark._score``,
and it had no tests: it was only ever exercised by running the whole evaluation,
which cannot tell a correct scorer from a flattering one. These pin the
definitions, because a metric that quietly means something else is worse than a
metric that is missing.
"""

from decimal import Decimal

from disclosure_rag.answer.models import Answer, Route, Status
from disclosure_rag.evaluation.benchmark import (
    Benchmark,
    BenchmarkReport,
    Case,
    Expectation,
    build_cases,
)
from disclosure_rag.ingest.chunker import Chunk
from disclosure_rag.labels.facts import Fact
from disclosure_rag.labels.ledger import FactLedger, LocatedFact
from disclosure_rag.provenance import Span
from disclosure_rag.retrieval.lexical import BM25Retriever

SPAN = Span(page=1, x0=0.1, y0=0.1, x1=0.2, y1=0.2)


class Scripted:
    """A pipeline that returns whatever the test says, keyed by question."""

    def __init__(self, answers: dict[str, Answer]) -> None:
        self.answers = answers

    def answer(self, question: str, document_id: str, top_k: int = 10) -> Answer:
        return self.answers[question]


def answered(question: str, value: str, route: Route = Route.LEDGER) -> Answer:
    return Answer(
        question=question,
        status=Status.ANSWERED,
        route=route,
        text=value,
        value=value,
        confidence=1.0,
        timings_ms={"route": 0.1},
    )


def abstained(question: str, route: Route = Route.PASSAGE) -> Answer:
    return Answer(
        question=question,
        status=Status.ABSTAINED,
        route=route,
        confidence=0.1,
        timings_ms={"route": 0.1},
    )


def score(cases: list[Case], answers: dict[str, Answer]) -> BenchmarkReport:
    benchmark = Benchmark(pipeline=Scripted(answers))  # type: ignore[arg-type]
    return benchmark.run(cases)


def figure(question: str, expected: str) -> Case:
    return Case(
        question=question,
        document_id="doc",
        expectation=Expectation.ANSWER_FROM_LEDGER,
        expected_value=expected,
    )


def unanswerable(question: str, note: str = "concept not tagged in this filing") -> Case:
    return Case(
        question=question,
        document_id="doc",
        expectation=Expectation.ABSTAIN,
        note=note,
    )


def test_a_right_value_by_the_wrong_route_is_not_routing_accuracy() -> None:
    """Routing and correctness are separate claims and are scored separately.

    A passage answer that happens to carry the right number does not mean the
    router worked, and conflating them would hide the failure this system's
    architecture exists to prevent.
    """
    cases = [figure("q1", "100")]
    report = score(cases, {"q1": answered("q1", "100", route=Route.PASSAGE)})
    assert report.answer_exact_match == 1.0
    assert report.routing_accuracy == 0.0


def test_an_answer_with_the_wrong_value_is_not_an_exact_match() -> None:
    cases = [figure("q1", "100")]
    report = score(cases, {"q1": answered("q1", "101")})
    assert report.routing_accuracy == 1.0
    assert report.answer_exact_match == 0.0


def test_abstaining_on_an_answerable_question_scores_zero_not_a_free_pass() -> None:
    """Declining everything would otherwise look like perfect precision."""
    cases = [figure("q1", "100")]
    report = score(cases, {"q1": abstained("q1")})
    assert report.answer_exact_match == 0.0
    assert report.abstention_precision == 0.0


def test_the_false_answer_rate_counts_any_answer_to_an_unanswerable_question() -> None:
    """Regardless of what it said. There was no right answer to give."""
    cases = [unanswerable("q1"), unanswerable("q2")]
    report = score(cases, {"q1": answered("q1", "whatever"), "q2": abstained("q2")})
    assert report.false_answer_rate == 0.5
    assert report.abstention_recall == 0.5


def test_recall_and_precision_are_not_the_same_measurement() -> None:
    """Recall is over questions that should be declined; precision is over
    abstentions actually made. A system that declines everything has recall 1.0
    and precision below it, and only reporting the first would hide that.
    """
    cases = [figure("q1", "100"), unanswerable("q2"), unanswerable("q3")]
    report = score(cases, {q: abstained(q) for q in ("q1", "q2", "q3")})
    assert report.abstention_recall == 1.0
    assert report.abstention_precision == 2 / 3


def test_a_trap_survives_only_when_no_figure_comes_back() -> None:
    cases = [unanswerable("t1", note="wrong period"), unanswerable("t2", note="wrong period")]
    report = score(cases, {"t1": abstained("t1"), "t2": answered("t2", "100")})
    assert report.wrong_period_traps == 2
    assert report.trap_survival == 0.5


def test_ambiguity_is_detected_only_by_declining() -> None:
    cases = [unanswerable("a1", note="ambiguous concept")]
    report = score(cases, {"a1": answered("a1", "100")})
    assert report.ambiguous_cases == 1
    assert report.ambiguity_detected == 0.0


def test_calibration_covers_answers_given_and_not_abstentions() -> None:
    """An abstention's confidence is a support score, not a claim that declining
    was right. Counting a correct 0.1-confidence abstention as accuracy 1.0
    would produce a large gap that means nothing."""
    cases = [figure("q1", "100"), unanswerable("q2")]
    report = score(cases, {"q1": answered("q1", "100"), "q2": abstained("q2")})
    assert report.calibration.samples == 1


def test_answering_an_unanswerable_question_counts_as_incorrect_in_calibration() -> None:
    cases = [unanswerable("q1")]
    report = score(cases, {"q1": answered("q1", "100")})
    assert report.calibration.samples == 1
    assert report.calibration.bins[-1].accuracy == 0.0


def test_empty_strata_do_not_divide_by_zero() -> None:
    report = score([figure("q1", "100")], {"q1": answered("q1", "100")})
    assert report.unanswerable == 0
    assert report.abstention_recall == 0.0
    assert report.trap_survival == 0.0


# Distinct enough to be told apart. An earlier version used "Label 0" through
# "Label 5", which all tokenise to the single term "label", so the router saw
# six concepts tied on the same wording and correctly declined as ambiguous.
LABELS = (
    "Bilanzsumme",
    "Umsatzerloese",
    "Herstellungskosten",
    "Zahlungsmittel",
    "Gewinnruecklage",
    "Grundkapital",
)


def build_ledger() -> FactLedger:
    rows = [
        LocatedFact(
            fact=Fact(
                fact_id=f"f{index}",
                concept=f"ifrs-full:C{index}",
                displayed=str(index),
                value=Decimal(index + 1),
                unit="EUR",
                period="instant:2022-12-31",
            ),
            span=SPAN,
        )
        for index in range(6)
    ]
    return FactLedger(
        document_id="doc",
        facts=rows,
        concept_labels={f"ifrs-full:C{index}": LABELS[index] for index in range(6)},
    )


def test_generated_cases_carry_every_expectation_class() -> None:
    cases = build_cases({"doc": build_ledger(), "other": build_ledger()})
    notes = {case.note for case in cases}
    assert Expectation.ANSWER_FROM_LEDGER in {case.expectation for case in cases}
    assert Expectation.ABSTAIN in {case.expectation for case in cases}
    assert "wrong period" in notes


def test_case_generation_is_stable_across_runs() -> None:
    """Seeded sampling, so a published case count is reproducible."""
    ledgers = {"doc": build_ledger()}
    assert [c.question for c in build_cases(ledgers)] == [c.question for c in build_cases(ledgers)]


def test_the_pipeline_and_the_scorer_agree_on_a_real_answer() -> None:
    """One case through the actual pipeline, so the scripted tests above are
    anchored to something real rather than to a fixture's idea of an Answer."""
    from disclosure_rag.answer.pipeline import AnswerPipeline

    ledger = build_ledger()
    retriever = BM25Retriever()
    retriever.index([Chunk(chunk_id="c0", document_id="doc", text="nichts", spans=[SPAN], order=0)])
    pipeline = AnswerPipeline({"doc": ledger}, retriever)

    case = figure("Wie hoch war Zahlungsmittel zum 31.12.2022?", "4")
    report = Benchmark(pipeline=pipeline).run([case])
    assert report.routing_accuracy == 1.0
    assert report.answer_exact_match == 1.0
