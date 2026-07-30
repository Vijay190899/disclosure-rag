"""Build the question set from the fact ledger.

Each question carries gold spans, so a run can be scored on *where* it pointed
and not only on what it said.

Strata are kept separate on purpose and are never pooled. ADR-0006 is explicit
about why: the exact-figure stratum is the easy control, and averaging it with
the hard cases would let good performance on lookups hide poor performance on
everything else. That is the precise failure this project exists to detect, so
building the metric in a way that could hide it would be self-defeating.
"""

from __future__ import annotations

import random
import re
from enum import StrEnum
from typing import NamedTuple

from pydantic import BaseModel, Field

from disclosure_rag.labels.ledger import FactLedger
from disclosure_rag.provenance import Span

CAMEL = re.compile(r"(?<!^)(?=[A-Z])")

# Fixed, so the sampled question set is identical on every run and any published
# number can be regenerated.
SAMPLE_SEED = 20260730


class Candidate(NamedTuple):
    """A concept and period eligible to become a question, before sampling."""

    key: tuple[str, str]
    fact_id: str
    subject: str
    label_source: str
    value: str


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
    period_hint: str = Field(
        default="",
        description="The period phrase, so a citation can pick the matching table column",
    )
    label_source: str = Field(
        default="own",
        description="'own' if the label came from this filing's linkbase, 'pooled' if another's",
    )


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


def _german_date(iso: str) -> str:
    """2022-12-31 becomes 31.12.2022, which is how the corpus writes dates."""
    parts = iso.split("-")
    if len(parts) != 3:
        return iso
    year, month, day = parts
    return f"{day}.{month}.{year}"


def describe_period(period: str) -> str:
    """Render a ledger period the way the documents write it.

    This was previously emitting ISO dates, which was quietly poisoning every
    query. The lexical tokenizer splits on hyphens, so "2022-01-01 bis
    2022-12-31" became six separate numeric tokens, `2022 01 01 2022 12 31`,
    against roughly four content tokens. Those numerals match figures on nearly
    every table page in a filing, so the period phrase was actively misleading
    retrieval rather than merely failing to help.

    German date format fixes both halves of that. It is what the filings
    actually print, and because the tokenizer treats a full stop as an internal
    separator, "31.12.2022" survives as a single token instead of three.
    """
    if period.startswith("instant:"):
        return f"zum {_german_date(period.removeprefix('instant:'))}"
    if "/" in period:
        start, end = period.split("/", 1)
        # A full financial year is how a reader would refer to it.
        if start.endswith("-01-01") and end.endswith("-12-31") and start[:4] == end[:4]:
            return f"im Geschäftsjahr {start[:4]}"
        return f"für den Zeitraum {_german_date(start)} bis {_german_date(end)}"
    return ""


def questions_from_ledger(
    ledger: FactLedger,
    limit_per_document: int = 40,
    pooled_labels: dict[str, str] | None = None,
) -> list[Question]:
    """Generate the exact-figure stratum, and the narrative stratum if available.

    ``pooled_labels`` supplies labels declared by *other* filings in the corpus,
    used when this filing does not declare one itself. Issuers must label their
    own extension concepts but standard IFRS labels come from the official
    taxonomy, which packages reference rather than bundle, so coverage varies
    from 92 of 92 concepts to 19 of 94 across three filings. Pooling lifts the
    worst case to 58 of 94.

    A pooled label is another issuer's wording for the same concept, so it will
    often not match the target document's phrasing. That is a feature: it
    creates the vocabulary mismatch a real user query has, and it is where dense
    retrieval should beat lexical matching. Questions record which source they
    came from so the two can be reported separately rather than confounded.

    The narrative stratum is drawn only from prose pairs marked ``confirmed``.
    Unconfirmed pairs are candidates, and roughly half of them are wrong, so
    using them unreviewed would put noise into the answer key. If none are
    confirmed the stratum is simply empty, and the report says so rather than
    quietly reporting a pooled number.
    """
    questions: list[Question] = []

    # Every location a given concept and period is tagged at. A figure is often
    # reported more than once, for example in a highlights table and again in the
    # full statement, and each occurrence is separately tagged. All of them are
    # correct answers to the same question, so all of them are gold.
    #
    # Getting this wrong was expensive to diagnose. Keeping only the first span
    # made dense retrieval look broken: it was returning the consolidated
    # statement on page 49 while the gold recorded page 25, and being scored zero
    # for finding a legitimate occurrence of exactly the right figure.
    locations: dict[tuple[str, str], list[Span]] = {}
    for row in ledger.facts:
        if not row.fact.concept:
            continue
        locations.setdefault((row.fact.concept, row.fact.period), []).append(row.span)

    # Exact figure: one question per distinct concept and period.
    #
    # Candidates are collected first and then sampled with a fixed seed. Taking
    # the first N in ledger order, which is what this did before, is a selection
    # bias: ledger order is document order, so the sample was the front of each
    # filing (primary statements) and never the notes.
    candidates: list[Candidate] = []
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
        # construction and would depress the score for no reason. ADR-0002.
        subject = ledger.concept_labels.get(fact.concept)
        label_source = "own"
        if not subject and pooled_labels:
            subject = pooled_labels.get(fact.concept)
            label_source = "pooled"
        if not subject:
            continue

        seen.add(key)
        candidates.append(
            Candidate(
                key=key,
                fact_id=fact.fact_id,
                subject=subject,
                label_source=label_source,
                value=str(fact.value),
            )
        )

    if limit_per_document and len(candidates) > limit_per_document:
        candidates = random.Random(SAMPLE_SEED).sample(candidates, limit_per_document)
    candidates.sort(key=lambda item: item.fact_id)  # stable order for reporting

    for candidate in candidates:
        period = describe_period(candidate.key[1])
        text = f"Wie hoch war {candidate.subject} {period}?".replace("  ", " ")
        questions.append(
            Question(
                question_id=f"{ledger.document_id}:ef:{candidate.fact_id}",
                document_id=ledger.document_id,
                text=text,
                stratum=Stratum.EXACT_FIGURE,
                gold_spans=locations[candidate.key],
                period_hint=period,
                gold_value=candidate.value,
                source_fact_id=candidate.fact_id,
                label_source=candidate.label_source,
            )
        )

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
