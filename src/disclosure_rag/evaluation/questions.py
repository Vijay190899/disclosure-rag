"""Build the question set from the fact ledger.

Each question carries gold spans, so a run can be scored on *where* it pointed
and not only on what it said.

Strata are kept separate on purpose and are never pooled. ADR-0008 is explicit
about why: the exact-figure stratum is the easy control, and averaging it with
the hard cases would let good performance on lookups hide poor performance on
everything else. That is the precise failure this project exists to detect, so
building the metric in a way that could hide it would be self-defeating.
"""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, Field

from disclosure_rag.labels.ledger import FactLedger
from disclosure_rag.provenance import Span

CAMEL = re.compile(r"(?<!^)(?=[A-Z])")


class Stratum(StrEnum):
    """Question difficulty classes, reported separately."""

    EXACT_FIGURE = "exact_figure"
    NARRATIVE = "narrative"
    UNANSWERABLE = "unanswerable"


class Question(BaseModel):
    """A question, its gold locations, and which stratum it belongs to."""

    model_config = {"frozen": True}

    question_id: str
    document_id: str
    text: str
    stratum: Stratum
    gold_spans: list[Span] = Field(default_factory=list)
    gold_value: str = ""
    source_fact_id: str = ""


def humanise_concept(concept: str) -> str:
    """Turn an XBRL concept name into something a person would ask about.

    "ifrs-full:PropertyPlantAndEquipment" becomes "property plant and
    equipment". Mechanical, so the phrasing is plain rather than natural. That
    is a known limitation of this stratum and part of why it is the easy
    control rather than the headline.
    """
    local = concept.split(":")[-1]
    words = CAMEL.sub(" ", local).lower().strip()
    return re.sub(r"\s+", " ", words)


def describe_period(period: str) -> str:
    """Render a ledger period as a phrase, in the language of the corpus."""
    if period.startswith("instant:"):
        return f"zum {period.removeprefix('instant:')}"
    if "/" in period:
        start, end = period.split("/", 1)
        return f"für den Zeitraum {start} bis {end}"
    return ""


def questions_from_ledger(ledger: FactLedger, limit_per_document: int = 40) -> list[Question]:
    """Generate the exact-figure stratum, and the narrative stratum if available.

    The narrative stratum is drawn only from prose pairs marked ``confirmed``.
    Unconfirmed pairs are candidates, and roughly half of them are wrong, so
    using them unreviewed would put noise into the answer key. If none are
    confirmed the stratum is simply empty, and the report says so rather than
    quietly reporting a pooled number.
    """
    questions: list[Question] = []

    # Exact figure: one question per distinct concept and period.
    seen: set[tuple[str, str]] = set()
    for row in ledger.facts:
        fact = row.fact
        key = (fact.concept, fact.period)
        if key in seen or not fact.concept:
            continue

        # The subject must be the label the issuer declared, not the concept
        # name. Concept names are English and these documents are German, so a
        # question built from one has no vocabulary in common with the text it
        # is asking about. A concept with no declared label is skipped rather
        # than asked about in English, because that question is unanswerable by
        # construction and would depress the score for no reason. ADR-0009.
        subject = ledger.concept_labels.get(fact.concept)
        if not subject:
            continue

        seen.add(key)
        period = describe_period(fact.period)
        text = f"Wie hoch war {subject} {period}?".replace("  ", " ")
        questions.append(
            Question(
                question_id=f"{ledger.document_id}:ef:{fact.fact_id}",
                document_id=ledger.document_id,
                text=text,
                stratum=Stratum.EXACT_FIGURE,
                gold_spans=[row.span],
                gold_value=str(fact.value),
                source_fact_id=fact.fact_id,
            )
        )
        if len(questions) >= limit_per_document:
            break

    for pair in ledger.prose_pairs:
        if not pair.confirmed:
            continue
        questions.append(
            Question(
                question_id=f"{ledger.document_id}:nr:{pair.fact_id}",
                document_id=ledger.document_id,
                text=pair.sentence,
                stratum=Stratum.NARRATIVE,
                gold_spans=[pair.gold_span],
                gold_value=str(pair.value),
                source_fact_id=pair.fact_id,
            )
        )

    return questions
