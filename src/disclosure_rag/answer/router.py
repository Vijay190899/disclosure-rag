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

# And the question must be substantially the label, not merely contain it.
#
# Containment on its own is not identification. "Erwerb von Sachanlagen" asks
# about a cash flow, and it contains the label "Sachanlagen", so a rule that
# only looks for the label returns the balance sheet carrying amount with full
# confidence. That is the exact failure this system claims not to have: a
# confidently wrong figure with an exact citation attached to it. Requiring the
# label to account for most of what the question actually names rules it out.
MIN_QUESTION_COVERAGE = 0.6

# Question framing rather than anything a filing tags. Kept short and literal:
# a long stopword list starts silently discarding words that are part of a
# concept name in some filing.
FRAMING = frozenset(
    {
        "wie",
        "hoch",
        "war",
        "waren",
        "ist",
        "sind",
        "der",
        "die",
        "das",
        "des",
        "dem",
        "den",
        "ein",
        "eine",
        "einer",
        "von",
        "vom",
        "und",
        "oder",
        "als",
        "aus",
        "auf",
        "bei",
        "mit",
        "fur",
        "für",
        "zum",
        "zur",
        "per",
        "sich",
        "wurde",
        "wurden",
        "betrug",
        "betrugen",
        "hohe",
        "höhe",
        "wert",
        # Period framing. "im Geschäftsjahr 2022" says which year, not which
        # figure, and counting it as something the question names made every
        # single-word concept look half specified.
        "geschaftsjahr",
        "geschäftsjahr",
        "jahr",
        "jahre",
        "zeitraum",
        "stichtag",
        "bis",
        "what",
        "was",
        "the",
        "for",
        "and",
        "how",
        "much",
        "value",
    }
)


def content_terms(question: str) -> set[str]:
    """What the question names, with the framing and the period taken out."""
    return {
        term
        for term in tokenize(question)
        if len(term) > 2 and term not in FRAMING and not term[0].isdigit()
    }


@dataclass(frozen=True)
class ConceptIndex:
    """Tagged concepts available for one document, keyed for lookup.

    Periods come only from this document's own facts, so a pooled label can
    never make the router claim a period the filing does not report.

    A concept carries several labels rather than one. Issuers must label their
    own extension concepts, but standard IFRS labels come from the official
    taxonomy, which packages reference rather than bundle. One filing in this
    corpus declares no labels at all, which left 323 tagged facts unreachable by
    the structured path. Borrowing another issuer's wording for the same concept
    fixes that, and keeping both wordings means the filer's own is still
    matched.
    """

    labels: dict[str, tuple[str, ...]] = field(default_factory=dict)
    periods: dict[str, set[str]] = field(default_factory=dict)

    @classmethod
    def from_ledger(cls, ledger: object, pooled: dict[str, set[str]] | None = None) -> ConceptIndex:
        from disclosure_rag.labels.ledger import FactLedger

        assert isinstance(ledger, FactLedger)
        periods: dict[str, set[str]] = {}
        for row in ledger.facts:
            periods.setdefault(row.fact.concept, set()).add(row.fact.period)

        labels: dict[str, tuple[str, ...]] = {}
        for concept in periods:
            wordings = set(pooled.get(concept, set())) if pooled else set()
            own = ledger.concept_labels.get(concept)
            if own:
                wordings.add(own)
            if wordings:
                labels[concept] = tuple(sorted(wordings))
        return cls(labels=labels, periods=periods)


def pool_labels(ledgers: dict[str, object]) -> dict[str, set[str]]:
    """Every wording any filing in the corpus declared, per concept.

    Extension concepts are namespaced per issuer, so they do not collide across
    filings and pooling them is a no-op rather than a hazard. Where two issuers
    word the same standard concept differently, both wordings are kept: a reader
    may use either, and a label that matches two concepts is already handled as
    ambiguous downstream rather than resolved arbitrarily.
    """
    from disclosure_rag.labels.ledger import FactLedger

    pooled: dict[str, set[str]] = {}
    for ledger in ledgers.values():
        assert isinstance(ledger, FactLedger)
        for concept, label in ledger.concept_labels.items():
            if label:
                pooled.setdefault(concept, set()).add(label)
    return pooled


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


def route_question(
    question: str,
    index: ConceptIndex,
    min_question_coverage: float = MIN_QUESTION_COVERAGE,
) -> RoutingDecision:
    """Route to the structured path when a tagged concept and period are both named.

    ``min_question_coverage`` is a parameter so the threshold can be swept
    against the benchmark rather than asserted.
    """
    question_terms = set(tokenize(question))
    if not question_terms:
        return RoutingDecision(Route.PASSAGE, reason="empty question")
    asked = content_terms(question)

    # Longest matching label wins, so "Summe Zinsaufwendungen" beats "Summe".
    # All concepts tying at the best score are kept: a label can be declared for
    # more than one concept, for example "Vorräte" for both the balance sheet
    # item and its cash flow adjustment, and picking one of those arbitrarily is
    # a confidently wrong answer.
    best_score = 0
    matches: list[tuple[str, str]] = []
    for concept, wordings in sorted(index.labels.items()):
        # A concept scores once, on its best-matching wording. Scoring each
        # wording separately would list the same concept twice and read as
        # ambiguity where there is none.
        best_for_concept = 0
        best_label = ""
        best_covered = -1
        for label in wordings:
            label_terms = [term for term in tokenize(label) if len(term) > 2]
            if len(label_terms) < MIN_LABEL_TOKENS:
                continue
            present = sum(1 for term in label_terms if term in question_terms)
            if present / len(label_terms) < MIN_LABEL_COVERAGE:
                continue
            # Ranked by how much of the label the question contains, and the
            # wording kept is the one that accounts for most of the question.
            # Those differ: a filing's own long wording and another issuer's
            # short one can both match, and reporting the short one would make
            # a fully specified question look underspecified.
            covered = len(asked & set(label_terms))
            if (present, covered) > (best_for_concept, best_covered):
                best_for_concept, best_covered, best_label = present, covered, label
        if not best_for_concept:
            continue
        if best_for_concept > best_score:
            best_score, matches = best_for_concept, [(concept, best_label)]
        elif best_for_concept == best_score:
            matches.append((concept, best_label))

    if not matches:
        return RoutingDecision(Route.PASSAGE, reason="no tagged concept named")

    concepts = tuple(concept for concept, _ in matches)
    label = matches[0][1]

    # The question has to be about the label, not merely contain it. Checked
    # against the best match, since every tied match scored the same.
    if asked:
        covered = len(asked & {term for term in tokenize(label) if len(term) > 2})
        if covered / len(asked) < min_question_coverage:
            return RoutingDecision(
                Route.PASSAGE,
                concepts=concepts,
                label=label,
                reason=(
                    f"the question names more than the tagged concept {label!r}, "
                    "so it is not asking for that figure"
                ),
            )
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
