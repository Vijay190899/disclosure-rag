"""End-to-end benchmark: does the system answer, route and abstain correctly?

Separate from the retrieval benchmark on purpose. Retrieval metrics score one
component; this scores the thing a user actually receives.

Three question classes, all generated mechanically so the whole suite reproduces
from a seed with no hand labelling and no API key:

**Answerable figures.** A concept and period the filer tagged. The system should
route to the structured layer and return the tagged value. Scored on routing
accuracy and exact numeric match.

**Unanswerable.** A concept the filer did not tag, or a period outside the
filing. Built by asking one document about another document's concepts, and by
asking for years the corpus does not cover. The system should abstain. Scored on
abstention precision and recall, because a tool whose selling point is
verifiability has to know when to say nothing.

**Wrong-period traps.** A tagged concept asked for a year it was not reported
for. These separate "knows the concept" from "knows the period", which is the
distinction a plausible wrong answer hides.

**Ambiguous concepts.** A concept tagged several times for one period with
different values, because it is reported per segment or component. The question
does not identify which, so the system should abstain rather than pick one.
"""

from __future__ import annotations

import random
import statistics
from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import BaseModel, Field

from disclosure_rag.answer.models import Route, Status
from disclosure_rag.answer.pipeline import AnswerPipeline
from disclosure_rag.answer.router import pool_labels
from disclosure_rag.evaluation.calibration import Calibration, calibrate
from disclosure_rag.labels.ledger import FactLedger
from disclosure_rag.periods import phrase_question

SEED = 20260730

# Years no filing in this corpus reports, for the unanswerable set.
IMPOSSIBLE_YEARS = ("2009", "2011", "2013")


class Expectation(StrEnum):
    """What a correct system does with this question."""

    ANSWER_FROM_LEDGER = "answer_from_ledger"
    ABSTAIN = "abstain"


@dataclass(frozen=True)
class Case:
    question: str
    document_id: str
    expectation: Expectation
    expected_value: str = ""
    note: str = ""


@dataclass
class Outcome:
    case: Case
    answered: bool
    route: Route
    value: str | None
    latency_ms: float
    confidence: float = 0.0
    exact_value: bool = False


class BenchmarkReport(BaseModel):
    """Standard end-to-end figures for a routed RAG system."""

    cases: int = 0

    answerable: int = 0
    routing_accuracy: float = Field(
        default=0.0, description="Share of answerable figures routed to the structured layer"
    )
    answer_exact_match: float = Field(
        default=0.0, description="Share of answerable figures returned with the tagged value"
    )

    unanswerable: int = 0
    abstention_recall: float = Field(
        default=0.0, description="Share of unanswerable questions correctly declined"
    )
    abstention_precision: float = Field(
        default=0.0, description="Share of abstentions that were correct to abstain"
    )
    false_answer_rate: float = Field(
        default=0.0, description="Share of unanswerable questions given a confident answer"
    )

    wrong_period_traps: int = 0
    trap_survival: float = Field(
        default=0.0,
        description="Share of wrong-period traps not answered with a figure",
    )
    ambiguous_cases: int = 0
    ambiguity_detected: float = Field(
        default=0.0,
        description="Share of dimensionally ambiguous questions declined rather than guessed",
    )

    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    calibration: Calibration = Field(default_factory=Calibration)


def build_cases(ledgers: dict[str, FactLedger], per_document: int = 20) -> list[Case]:
    """Generate the three question classes from the ledgers.

    Labels are pooled across the corpus the same way the serving router pools
    them. Asking only with a filing's own wordings would leave the filing that
    declares none untested, which is precisely the filing where the structured
    path is hardest.
    """
    rng = random.Random(SEED)
    cases: list[Case] = []
    document_ids = sorted(ledgers)
    pooled = pool_labels(dict(ledgers))

    for document_id in document_ids:
        ledger = ledgers[document_id]
        wordings = {
            concept: sorted(pooled.get(concept, set()) | {ledger.concept_labels.get(concept, "")})
            for concept in {row.fact.concept for row in ledger.facts}
        }
        wordings = {
            concept: [label for label in labels if label] for concept, labels in wordings.items()
        }
        labelled = [
            row for row in ledger.facts if wordings.get(row.fact.concept) and row.fact.period
        ]
        if not labelled:
            continue

        # Group by concept and period so ambiguity is visible rather than hidden
        # by taking the first value.
        values: dict[tuple[str, str], set[str]] = {}
        for row in labelled:
            values.setdefault((row.fact.concept, row.fact.period), set()).add(str(row.fact.value))

        # Answerable: tagged, and unambiguous for that period.
        pool: list[tuple[str, str, str]] = []
        ambiguous: list[tuple[str, str]] = []
        for (concept, period), distinct in values.items():
            # The filer's own wording when it has one, so a question reads the
            # way that filing writes it. Sorted for determinism otherwise.
            label = ledger.concept_labels.get(concept) or wordings[concept][0]
            if len(distinct) > 1:
                ambiguous.append((label, period))
            else:
                pool.append((label, period, next(iter(distinct))))
        if not pool:
            continue
        for label, period, value in rng.sample(pool, min(per_document, len(pool))):
            cases.append(
                Case(
                    question=phrase_question(label, period),
                    document_id=document_id,
                    expectation=Expectation.ANSWER_FROM_LEDGER,
                    expected_value=value,
                )
            )

        # Wrong-period trap: real concept, a year it was not reported for.
        tagged_years = {
            year for _, period, _ in pool for year in period.split("/") if year[:4].isdigit()
        }
        for label, _period, _ in rng.sample(pool, min(per_document // 2, len(pool))):
            year = rng.choice(IMPOSSIBLE_YEARS)
            if any(year in known for known in tagged_years):
                continue
            cases.append(
                Case(
                    question=f"Wie hoch war {label} im Geschäftsjahr {year}?",
                    document_id=document_id,
                    expectation=Expectation.ABSTAIN,
                    note="wrong period",
                )
            )

        # Ambiguous: tagged several times for the period with different values.
        for label, period in rng.sample(ambiguous, min(per_document // 2, len(ambiguous))):
            cases.append(
                Case(
                    question=phrase_question(label, period),
                    document_id=document_id,
                    expectation=Expectation.ABSTAIN,
                    note="ambiguous concept",
                )
            )

        # Unanswerable: another filing's concept, which this one did not tag.
        #
        # The test is "did not tag", not "did not label". Those used to coincide
        # closely enough to be interchangeable and pooling separated them: a
        # filing can tag a concept while declaring no wording for it, and a
        # borrowed wording then reaches a figure that really is in the filing.
        # Keeping the old filter would have counted correct answers as false
        # ones, on the filing with no labels most of all.
        tagged = {row.fact.concept for row in ledger.facts}
        reachable = {
            label
            for concept in tagged
            for label in (pooled.get(concept, set()) | {ledger.concept_labels.get(concept, "")})
            if label
        }
        others = [other for other in document_ids if other != document_id]
        foreign = [
            label
            for other in others
            for concept, label in ledgers[other].concept_labels.items()
            if concept not in tagged and label not in reachable
        ]
        for label in rng.sample(foreign, min(per_document // 2, len(foreign))):
            cases.append(
                Case(
                    question=f"Wie hoch war {label} zum 31.12.2022?",
                    document_id=document_id,
                    expectation=Expectation.ABSTAIN,
                    note="concept not tagged in this filing",
                )
            )

    return cases


@dataclass
class Benchmark:
    pipeline: AnswerPipeline
    outcomes: list[Outcome] = field(default_factory=list)

    def run(self, cases: list[Case]) -> BenchmarkReport:
        self.outcomes = []
        for case in cases:
            answer = self.pipeline.answer(case.question, case.document_id)
            latency = sum(answer.timings_ms.values())
            self.outcomes.append(
                Outcome(
                    case=case,
                    answered=answer.status is Status.ANSWERED,
                    route=answer.route,
                    value=answer.value,
                    latency_ms=latency,
                    confidence=answer.confidence,
                    exact_value=bool(answer.value and answer.value == case.expected_value),
                )
            )
        return self._score()

    def _score(self) -> BenchmarkReport:
        answerable = [
            o for o in self.outcomes if o.case.expectation is Expectation.ANSWER_FROM_LEDGER
        ]
        abstainable = [o for o in self.outcomes if o.case.expectation is Expectation.ABSTAIN]
        traps = [o for o in abstainable if o.case.note == "wrong period"]
        ambiguous = [o for o in abstainable if o.case.note == "ambiguous concept"]

        abstained = [o for o in self.outcomes if not o.answered]
        correct_abstentions = [o for o in abstained if o.case.expectation is Expectation.ABSTAIN]
        latencies = sorted(o.latency_ms for o in self.outcomes) or [0.0]

        def share(numerator: int, denominator: int) -> float:
            return numerator / denominator if denominator else 0.0

        return BenchmarkReport(
            cases=len(self.outcomes),
            answerable=len(answerable),
            routing_accuracy=share(
                sum(1 for o in answerable if o.route is Route.LEDGER), len(answerable)
            ),
            answer_exact_match=share(sum(1 for o in answerable if o.exact_value), len(answerable)),
            unanswerable=len(abstainable),
            abstention_recall=share(
                sum(1 for o in abstainable if not o.answered), len(abstainable)
            ),
            abstention_precision=share(len(correct_abstentions), len(abstained)),
            false_answer_rate=share(sum(1 for o in abstainable if o.answered), len(abstainable)),
            wrong_period_traps=len(traps),
            trap_survival=share(sum(1 for o in traps if o.value is None), len(traps)),
            ambiguous_cases=len(ambiguous),
            ambiguity_detected=share(sum(1 for o in ambiguous if not o.answered), len(ambiguous)),
            # Calibration is measured over answers the system actually gave.
            # Including abstentions would conflate two different questions: an
            # abstention's confidence is a support score for a passage, not a
            # prediction that abstaining was right, and scoring a correct
            # 0.0-confidence abstention as accuracy 1.0 produces a large gap
            # that means nothing.
            #
            # Answering a question that had no answer is counted as incorrect
            # regardless of the value returned, because it is.
            calibration=calibrate(
                [
                    (
                        o.confidence,
                        o.exact_value
                        if o.case.expectation is Expectation.ANSWER_FROM_LEDGER
                        else False,
                    )
                    for o in self.outcomes
                    if o.answered
                ]
            ),
            p50_latency_ms=round(statistics.median(latencies), 2),
            p95_latency_ms=round(latencies[min(int(len(latencies) * 0.95), len(latencies) - 1)], 2),
        )


def risk_coverage(
    pipeline: AnswerPipeline, cases: list[Case], thresholds: tuple[float, ...]
) -> list[tuple[float, float, float]]:
    """Sweep the abstention threshold and report coverage against error.

    The standard way to choose an abstention point, and the honest way to present
    one: a threshold is a trade, not a setting, so the curve belongs in the
    results rather than a single number chosen quietly.

    Returns (threshold, coverage, false answer rate), where coverage is the share
    of answerable questions still answered and the false answer rate is the share
    of unanswerable ones wrongly answered.
    """
    original = pipeline.abstain_below
    curve: list[tuple[float, float, float]] = []
    try:
        for threshold in thresholds:
            pipeline.abstain_below = threshold
            report = Benchmark(pipeline).run(cases)
            coverage = report.routing_accuracy and report.answer_exact_match
            curve.append((threshold, coverage, report.false_answer_rate))
    finally:
        pipeline.abstain_below = original
    return curve


def render_risk_coverage(curve: list[tuple[float, float, float]]) -> str:
    lines = [
        "",
        "Abstention threshold sweep",
        "",
        "| Threshold | Exact match on answerable | False answer rate on unanswerable |",
        "|---|---|---|",
    ]
    lines.extend(
        f"| {threshold:.2f} | {coverage:.3f} | {error:.3f} |"
        for threshold, coverage, error in curve
    )
    return "\n".join(lines)


def render_report(report: BenchmarkReport) -> str:
    return "\n".join(
        [
            "",
            f"End to end, {report.cases} generated cases",
            "",
            "| Measure | n | Result |",
            "|---|---|---|",
            f"| Routing accuracy, tagged figures | {report.answerable} "
            f"| {report.routing_accuracy:.3f} |",
            f"| Answer exact match, tagged figures | {report.answerable} "
            f"| {report.answer_exact_match:.3f} |",
            f"| Abstention recall, unanswerable | {report.unanswerable} "
            f"| {report.abstention_recall:.3f} |",
            f"| Abstention precision | {report.unanswerable} | {report.abstention_precision:.3f} |",
            f"| False answer rate, unanswerable | {report.unanswerable} "
            f"| {report.false_answer_rate:.3f} |",
            f"| Wrong-period traps survived | {report.wrong_period_traps} "
            f"| {report.trap_survival:.3f} |",
            f"| Dimensional ambiguity detected | {report.ambiguous_cases} "
            f"| {report.ambiguity_detected:.3f} |",
            f"| Latency p50 / p95 (ms) | {report.cases} "
            f"| {report.p50_latency_ms:.2f} / {report.p95_latency_ms:.2f} |",
        ]
    )
