"""Tests for question generation and scoring."""

from decimal import Decimal

from disclosure_rag.evaluation.metrics import Result, score_run
from disclosure_rag.evaluation.questions import (
    Question,
    Stratum,
    describe_period,
    humanise_concept,
    questions_from_ledger,
)
from disclosure_rag.labels.facts import Fact
from disclosure_rag.labels.ledger import FactLedger, LocatedFact, ProsePair
from disclosure_rag.provenance import Span

GOLD = Span(page=2, x0=0.10, y0=0.10, x1=0.30, y1=0.20)
BLOCK = Span(page=2, x0=0.05, y0=0.05, x1=0.60, y1=0.30)  # a text block containing GOLD
ELSEWHERE = Span(page=2, x0=0.70, y0=0.70, x1=0.90, y1=0.80)
WRONG_PAGE = Span(page=5, x0=0.10, y0=0.10, x1=0.30, y1=0.20)


def test_concept_names_become_readable() -> None:
    assert humanise_concept("ifrs-full:PropertyPlantAndEquipment") == "property plant and equipment"


def test_instant_and_duration_periods_read_differently() -> None:
    assert describe_period("instant:2022-12-31") == "as at 2022-12-31"
    assert "2022-01-01 to 2022-12-31" in describe_period("2022-01-01/2022-12-31")


def ledger_with(prose_confirmed: bool | None = None) -> FactLedger:
    fact = Fact(
        fact_id="f1",
        concept="ifrs-full:Assets",
        displayed="5.996,4",
        value=Decimal("5996400000"),
        period="instant:2022-12-31",
    )
    pairs = []
    if prose_confirmed is not None:
        pairs = [
            ProsePair(
                document_id="doc",
                sentence="Die Gesamtaktiva beliefen sich auf EUR 5.996,4 Mio.",
                mention="5.996,4",
                page=2,
                fact_id="f1",
                concept="ifrs-full:Assets",
                value=Decimal("5996400000"),
                gold_span=GOLD,
                confirmed=prose_confirmed,
            )
        ]
    return FactLedger(
        document_id="doc",
        facts=[LocatedFact(fact=fact, span=GOLD)],
        prose_pairs=pairs,
    )


def test_exact_figure_questions_carry_gold_spans() -> None:
    questions = questions_from_ledger(ledger_with())
    assert len(questions) == 1
    assert questions[0].stratum == Stratum.EXACT_FIGURE
    assert questions[0].gold_spans == [GOLD]
    assert "assets" in questions[0].text.lower()


def test_unconfirmed_prose_pairs_are_not_used_as_questions() -> None:
    """Roughly half the candidates are wrong, so unreviewed ones are noise."""
    strata = {q.stratum for q in questions_from_ledger(ledger_with(prose_confirmed=False))}
    assert Stratum.NARRATIVE not in strata


def test_confirmed_prose_pairs_become_narrative_questions() -> None:
    strata = {q.stratum for q in questions_from_ledger(ledger_with(prose_confirmed=True))}
    assert Stratum.NARRATIVE in strata


def question(question_id: str = "q1") -> Question:
    return Question(
        question_id=question_id,
        document_id="doc",
        text="What was assets?",
        stratum=Stratum.EXACT_FIGURE,
        gold_spans=[GOLD],
    )


def test_a_hit_at_rank_one_scores_everywhere() -> None:
    result = Result(question_id="q1", stratum=Stratum.EXACT_FIGURE, retrieved_spans=[[BLOCK]])
    score = score_run([question()], {"q1": result})[0]
    assert score.recall_at_1 == 1.0
    assert score.citation_coverage_at_1 == 1.0


def test_recall_and_citation_accuracy_can_disagree() -> None:
    """The gap this project exists to measure.

    The right passage is retrieved, but not at rank one, so what a reader would
    actually be shown points somewhere else. Recall@5 sees a success; citation
    accuracy sees a failure. Reporting only the first would hide it.
    """
    result = Result(
        question_id="q1",
        stratum=Stratum.EXACT_FIGURE,
        retrieved_spans=[[ELSEWHERE], [BLOCK]],
    )
    score = score_run([question()], {"q1": result})[0]
    assert score.recall_at_5 == 1.0
    assert score.recall_at_1 == 0.0
    assert score.citation_coverage_at_1 == 0.0


def test_the_right_box_on_the_wrong_page_is_a_miss() -> None:
    result = Result(question_id="q1", stratum=Stratum.EXACT_FIGURE, retrieved_spans=[[WRONG_PAGE]])
    score = score_run([question()], {"q1": result})[0]
    assert score.citation_coverage_at_1 == 0.0
    assert score.recall_at_10 == 0.0


def test_a_question_with_no_result_counts_as_a_miss() -> None:
    """Otherwise a retriever could improve its score by returning nothing."""
    score = score_run([question()], {})[0]
    assert score.questions == 1
    assert score.recall_at_10 == 0.0


def test_strata_are_scored_separately() -> None:
    questions = [
        question("q1"),
        Question(
            question_id="q2",
            document_id="doc",
            text="narrative",
            stratum=Stratum.NARRATIVE,
            gold_spans=[GOLD],
        ),
    ]
    results = {
        "q1": Result(question_id="q1", stratum=Stratum.EXACT_FIGURE, retrieved_spans=[[BLOCK]]),
        "q2": Result(question_id="q2", stratum=Stratum.NARRATIVE, retrieved_spans=[[ELSEWHERE]]),
    }
    scores = {s.stratum: s for s in score_run(questions, results)}
    assert scores[Stratum.EXACT_FIGURE].recall_at_1 == 1.0
    assert scores[Stratum.NARRATIVE].recall_at_1 == 0.0


def test_empty_strata_are_omitted_rather_than_reported_as_zero() -> None:
    scores = score_run([question()], {})
    assert {s.stratum for s in scores} == {Stratum.EXACT_FIGURE}
