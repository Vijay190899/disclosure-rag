"""Decide whether a question has a structured answer.

A question resolves to the structured path when it names a concept the filer has
tagged and a period that concept was reported for. Both halves are required: a
concept without a period is ambiguous across years, which is the failure that
makes text retrieval unreliable on these questions in the first place.

Deterministic on purpose. A model in front of a database lookup would add
latency and a failure mode in exchange for nothing, and the routing decision has
to be explainable when a citation is challenged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from disclosure_rag.answer.models import Route
from disclosure_rag.retrieval.lexical import tokenize

# 31.12.2022 or 2022. Both are how the corpus and its readers write periods.
GERMAN_DATE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.((?:19|20)\d{2})\b")
YEAR = re.compile(r"\b((?:19|20)\d{2})\b")

# A concept label must be substantially present in the question, not merely
# share a word with it. "Bilanzsumme" against a question about the balance sheet
# is a match; "Summe" on its own is not.
MIN_LABEL_COVERAGE = 0.8
MIN_LABEL_TOKENS = 1


@dataclass(frozen=True)
class ConceptIndex:
    """Tagged concepts available for one document, keyed for lookup.

    Built from the fact ledger, so it reflects exactly what the filer tagged.
    """

    labels: dict[str, str] = field(default_factory=dict)
    periods: dict[str, set[str]] = field(default_factory=dict)

    @classmethod
    def from_ledger(cls, ledger: object) -> ConceptIndex:
        from disclosure_rag.labels.ledger import FactLedger

        assert isinstance(ledger, FactLedger)
        periods: dict[str, set[str]] = {}
        for row in ledger.facts:
            periods.setdefault(row.fact.concept, set()).add(row.fact.period)
        return cls(labels=dict(ledger.concept_labels), periods=periods)


@dataclass(frozen=True)
class RoutingDecision:
    route: Route
    concepts: tuple[str, ...] = ()
    period: str = ""
    label: str = ""
    reason: str = ""

    @property
    def concept(self) -> str:
        """The single matched concept, or empty when the label is ambiguous."""
        return self.concepts[0] if len(self.concepts) == 1 else ""


def _periods_in(question: str) -> set[str]:
    """Period markers a reader would write, normalised to what the ledger holds."""
    found: set[str] = set()
    for day, month, year in GERMAN_DATE.findall(question):
        found.add(f"instant:{year}-{int(month):02d}-{int(day):02d}")
        found.add(year)
    found.update(YEAR.findall(question))
    return found


def _match_period(wanted: set[str], available: set[str]) -> str:
    """Prefer an exact instant, fall back to a period containing the year."""
    for candidate in available:
        if candidate in wanted:
            return candidate
    for candidate in sorted(available):
        years = set(YEAR.findall(candidate))
        if years & wanted:
            return candidate
    return ""


def route_question(question: str, index: ConceptIndex) -> RoutingDecision:
    """Route to the structured path when a tagged concept and period are both named."""
    question_terms = set(tokenize(question))
    if not question_terms:
        return RoutingDecision(Route.PASSAGE, reason="empty question")

    # Longest matching label wins, so "Summe Zinsaufwendungen" beats "Summe".
    # All concepts tying at the best score are kept: a label can be declared for
    # more than one concept, for example "Vorräte" for both the balance sheet
    # item and its cash flow adjustment, and picking one of those arbitrarily is
    # a confidently wrong answer.
    best_score = 0
    matches: list[tuple[str, str]] = []
    for concept, label in sorted(index.labels.items()):
        label_terms = [term for term in tokenize(label) if len(term) > 2]
        if len(label_terms) < MIN_LABEL_TOKENS:
            continue
        present = sum(1 for term in label_terms if term in question_terms)
        if present / len(label_terms) < MIN_LABEL_COVERAGE:
            continue
        if present > best_score:
            best_score, matches = present, [(concept, label)]
        elif present == best_score:
            matches.append((concept, label))

    if not matches:
        return RoutingDecision(Route.PASSAGE, reason="no tagged concept named")

    concepts = tuple(concept for concept, _ in matches)
    label = matches[0][1]
    wanted = _periods_in(question)
    if not wanted:
        return RoutingDecision(
            Route.PASSAGE,
            concepts=concepts,
            label=label,
            reason="concept named but no period, which is ambiguous across years",
        )

    available: set[str] = set()
    for concept in concepts:
        available |= index.periods.get(concept, set())
    period = _match_period(wanted, available)
    if not period:
        return RoutingDecision(
            Route.PASSAGE,
            concepts=concepts,
            label=label,
            reason="concept named but not tagged for the requested period",
        )

    return RoutingDecision(Route.LEDGER, concepts=concepts, period=period, label=label)
