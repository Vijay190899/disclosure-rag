"""Questions each filing can actually answer.

A demo whose prefilled question abstains teaches the wrong lesson about the
system. So rather than guessing at plausible questions, this proposes candidates
from the filing's own tags and then **asks them**, keeping only the ones that
come back answered with an exact citation. An example that does not work is
never offered, because it was tried first.

The cost is a handful of ledger lookups per filing at startup, which is
microseconds. The benefit is that the first thing anyone does with the service
succeeds and shows the point of it.
"""

from __future__ import annotations

import random
from collections.abc import Callable

from disclosure_rag.answer.models import Answer
from disclosure_rag.labels.ledger import FactLedger
from disclosure_rag.periods import phrase_question

SEED = 20240817
ATTEMPTS = 40


def candidates(ledger: FactLedger, pooled: dict[str, set[str]] | None = None) -> list[str]:
    """Figure questions this filing plausibly supports, in a stable order.

    Concepts tagged more than once for the same period are skipped: those are
    the dimensionally ambiguous ones the system declines by design, and offering
    one as an example would advertise an abstention.

    ``pooled`` supplies wordings declared by other filings, matching what the
    router will accept. Without it the filing that declares no labels of its own
    would be offered nothing, which is the filing whose examples matter most.
    """

    def wordings(concept: str) -> list[str]:
        own = ledger.concept_labels.get(concept, "")
        borrowed = pooled.get(concept, set()) if pooled else set()
        return sorted({label for label in {own, *borrowed} if label})

    values: dict[tuple[str, str], set[str]] = {}
    for row in ledger.facts:
        fact = row.fact
        if fact.period and wordings(fact.concept):
            values.setdefault((fact.concept, fact.period), set()).add(str(fact.value))

    unambiguous = sorted(
        (wordings(concept)[0], period)
        for (concept, period), distinct in values.items()
        if len(distinct) == 1
    )
    rng = random.Random(SEED)
    rng.shuffle(unambiguous)
    return [phrase_question(label, period) for label, period in unambiguous[:ATTEMPTS]]


def working_examples(
    ledger: FactLedger,
    ask: Callable[[str], Answer],
    limit: int = 3,
    pooled: dict[str, set[str]] | None = None,
) -> list[str]:
    """Candidates filtered down to those that answer with an exact citation."""
    kept: list[str] = []
    for question in candidates(ledger, pooled):
        if len(kept) == limit:
            break
        answer = ask(question)
        if answer.answered and any(citation.exact for citation in answer.citations):
            kept.append(question)
    return kept
