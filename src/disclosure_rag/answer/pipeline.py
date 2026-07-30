"""The end-to-end answer pipeline.

Route, answer, decide whether the answer is supported well enough to return, and
time every stage.

Abstention is a designed output rather than an error path. In a document a reader
has to verify, an unsupported answer costs more than no answer, so the threshold
is a product decision and it is configurable.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal

from disclosure_rag.answer.generators import ExtractiveGenerator, Generator
from disclosure_rag.answer.models import Answer, Citation, Route, Status
from disclosure_rag.answer.router import ConceptIndex, route_question
from disclosure_rag.labels.ledger import FactLedger
from disclosure_rag.retrieval.base import Retriever


def _format_figure(value: Decimal, unit: str) -> str:
    """Render a figure the way the corpus does: 1.204.000,00 rather than 1204000.0.

    Always two decimal places. Reading a monetary amount back as "192.900.000,0"
    invites a misread of the last digit, which is the kind of detail that costs
    trust in a tool whose whole job is being checkable.
    """
    quantised = value.quantize(Decimal("0.01"))
    whole, _, fraction = f"{abs(quantised):f}".partition(".")
    grouped = f"{int(whole):,}".replace(",", ".")
    rendered = f"{grouped},{fraction.ljust(2, '0')[:2]}"
    sign = "-" if value < 0 else ""
    return f"{sign}{rendered} {unit}".strip()


class AnswerPipeline:
    """Answers questions about one corpus of filings."""

    def __init__(
        self,
        ledgers: dict[str, FactLedger],
        retriever: Retriever,
        generator: Generator | None = None,
        abstain_below: float = 0.8,
    ) -> None:
        self.ledgers = ledgers
        self.retriever = retriever
        self.generator = generator or ExtractiveGenerator()
        self.abstain_below = abstain_below
        self.indexes = {
            document_id: ConceptIndex.from_ledger(ledger) for document_id, ledger in ledgers.items()
        }

    @contextmanager
    def _timed(self, timings: dict[str, float], stage: str) -> Iterator[None]:
        start = time.perf_counter()
        try:
            yield
        finally:
            timings[stage] = round((time.perf_counter() - start) * 1000, 2)

    def answer(self, question: str, document_id: str, top_k: int = 10) -> Answer:
        timings: dict[str, float] = {}
        ledger = self.ledgers.get(document_id)
        if ledger is None:
            return Answer(
                question=question,
                status=Status.ABSTAINED,
                route=Route.NONE,
                reason=f"unknown document {document_id!r}",
            )

        with self._timed(timings, "route"):
            decision = route_question(question, self.indexes[document_id])

        if decision.route is Route.LEDGER:
            with self._timed(timings, "ledger"):
                answer = self._from_ledger(question, ledger, decision.concepts, decision.period)
            answer.timings_ms = timings
            return answer

        with self._timed(timings, "retrieve"):
            hits = self.retriever.search(question, top_k=top_k, document_id=document_id)
        with self._timed(timings, "generate"):
            generated = self.generator.generate(question, hits)

        if not generated.text or generated.support < self.abstain_below:
            return Answer(
                question=question,
                status=Status.ABSTAINED,
                route=Route.PASSAGE,
                confidence=round(generated.support, 3),
                reason=decision.reason
                or f"support {generated.support:.2f} below threshold {self.abstain_below}",
                citations=generated.citations[:1],
                timings_ms=timings,
            )

        return Answer(
            question=question,
            status=Status.ANSWERED,
            route=Route.PASSAGE,
            text=generated.text,
            citations=generated.citations,
            confidence=round(generated.support, 3),
            timings_ms=timings,
        )

    def _from_ledger(
        self, question: str, ledger: FactLedger, concepts: tuple[str, ...], period: str
    ) -> Answer:
        """Answer from the tagged facts.

        The citation is the tag's own location, so it is exact rather than
        predicted. That is recorded on the citation itself so downstream
        reporting never scores it as an estimate.
        """
        rows = [
            row
            for row in ledger.facts
            if row.fact.concept in concepts and row.fact.period == period
        ]
        if not rows:
            return Answer(
                question=question,
                status=Status.ABSTAINED,
                route=Route.LEDGER,
                reason=f"{', '.join(concepts)} not tagged for {period}",
            )

        # A concept can be tagged several times for one period, dimensionally
        # qualified: equity at a date is reported per component, revenue per
        # segment. The question as asked does not say which, so answering with
        # one of them is a confidently wrong answer, which is the failure this
        # system exists to avoid. Measured at 7.1% of concept and period keys.
        distinct = {str(row.fact.value) for row in rows}
        if len(distinct) > 1:
            return Answer(
                question=question,
                status=Status.ABSTAINED,
                route=Route.LEDGER,
                reason=(
                    f"the question matches {len(distinct)} different tagged values for "
                    f"{period}, so it does not identify one. A figure can be reported per "
                    "segment or component, and one label can be declared for more than "
                    "one concept."
                ),
                citations=[
                    Citation(
                        document_id=ledger.document_id,
                        page=row.span.page,
                        spans=[row.span],
                        quote=row.fact.displayed,
                        exact=True,
                    )
                    for row in rows[:5]
                ],
            )

        fact = rows[0].fact
        citations = [
            Citation(
                document_id=ledger.document_id,
                page=row.span.page,
                spans=[row.span],
                quote=row.fact.displayed,
                exact=True,
            )
            for row in rows
        ]
        return Answer(
            question=question,
            status=Status.ANSWERED,
            route=Route.LEDGER,
            text=_format_figure(fact.value, fact.unit),
            value=str(fact.value),
            unit=fact.unit or None,
            period=period,
            citations=citations,
            confidence=1.0,
        )
