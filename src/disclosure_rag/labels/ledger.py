"""The fact ledger, and the prose pairs drawn from it.

Two outputs, for two different jobs.

The **ledger** is one row per tagged fact: what the number means and where it
sits. It supplies gold boxes for citation scoring and exact answers for numeric
questions.

The **prose pairs** are narrative sentences whose figure resolves to a tagged
fact. They exist because the M0 probe measured a 38% resolution rate, which is
too thin to build reconciliation on but ample to build an evaluation stratum
from: a feature must work on most inputs, an evaluation set only has to be
correct on the inputs it contains. Without them the benchmark would be built
entirely from tagged primary-statement figures, which is the degenerate case
ADR-0003 warned about and ADR-0008 exists to prevent.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, Field

from disclosure_rag.labels.facts import Fact
from disclosure_rag.labels.locate import Confirmation
from disclosure_rag.provenance import Span

NUMBER = re.compile(r"(?<![\w.,])-?\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?(?![\w])")
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
WORD = re.compile(r"[^\W\d_]{3,}", re.UNICODE)

# Prose detection. A narrative claim is a sentence; a table row is not. Three
# cheap signals together separate them: long enough, enough real words, and not
# mostly digits. "Gesamt 197.315 737.935 4.230.415" fails the last two.
MIN_SENTENCE_CHARS = 60
MIN_SENTENCE_WORDS = 8
MAX_DIGIT_RATIO = 0.20

# A prose figure agrees with a tagged fact when it matches at the precision the
# prose itself uses. "rund 1,2 Mrd" agrees with 1204000000; "1,3 Mrd" does not.
MATCH_TOLERANCE = Decimal("0.005")
SCALE_CANDIDATES = (Decimal(1), Decimal(1_000), Decimal(1_000_000), Decimal(1_000_000_000))

# Matching on value alone produces coincidences: in a document holding hundreds
# of facts, a bare "149" will equal something. A figure needs enough significant
# digits for the match to carry information. Measured on the Austrian corpus,
# this is what separates a real restatement from an accident.
MIN_SIGNIFICANT_DIGITS = 4


class LocatedFact(BaseModel):
    """A tagged fact together with where it sits on the printed page."""

    model_config = {"frozen": True}

    fact: Fact
    span: Span


class ProsePair(BaseModel):
    """A candidate narrative restatement of a tagged fact.

    The gold span is the tagged fact's location. The system under test never
    sees the tag, so answering still requires retrieval from the rendered page.

    **These are candidates, not labels.** Two failure modes survive the filters
    and both need a human to catch them: layout blocks that are really table
    rows but read as prose, and value matches that are coincidence rather than
    restatement. On the Austrian corpus roughly half of the candidates inspected
    were genuine. Only rows with ``confirmed`` set belong in an evaluation set.
    """

    model_config = {"frozen": True}

    document_id: str
    sentence: str
    mention: str = Field(description="The figure as written in the prose")
    page: int
    fact_id: str
    concept: str
    value: Decimal
    gold_span: Span
    confirmed: bool = Field(
        default=False,
        description="Set by hand review. Unconfirmed pairs must not be used as labels.",
    )


class FactLedger(BaseModel):
    """Everything the label plane knows about one document."""

    document_id: str
    facts: list[LocatedFact] = Field(default_factory=list)
    prose_pairs: list[ProsePair] = Field(default_factory=list)
    coverage: float = Field(default=0.0, description="Share of facts that were located")
    confirmation: Confirmation = Field(default_factory=Confirmation)

    def spans_for(self, fact_id: str) -> list[Span]:
        return [item.span for item in self.facts if item.fact.fact_id == fact_id]

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")

    @classmethod
    def read(cls, path: Path) -> FactLedger:
        return cls.model_validate_json(path.read_text(encoding="utf-8"))


def sentence_around(text: str, position: int) -> str:
    """The sentence containing a character position."""
    start = 0
    for piece in SENTENCE_SPLIT.split(text):
        end = start + len(piece)
        if start <= position <= end:
            return piece.strip()
        start = end + 1
    return text.strip()


def is_prose(sentence: str) -> bool:
    """True for something written as a sentence, false for a table row."""
    if len(sentence) < MIN_SENTENCE_CHARS:
        return False
    if len(WORD.findall(sentence)) < MIN_SENTENCE_WORDS:
        return False
    digits = sum(character.isdigit() for character in sentence)
    return digits / len(sentence) < MAX_DIGIT_RATIO


def is_specific(mention: str) -> bool:
    """True if a figure carries enough digits for a value match to mean something.

    Guards against coincidence. Across three filings holding 865 facts, bare
    three-digit numbers such as "149" or "202" match some fact almost always,
    and those matches carry no information.
    """
    return sum(character.isdigit() for character in mention) >= MIN_SIGNIFICANT_DIGITS


def resolve_to_fact(value: Decimal, facts: list[Fact]) -> Fact | None:
    """Find the tagged fact a prose figure restates, if any.

    Tries the figure as written and at each common scale, because prose says
    "1,2 Mrd" where the statement tags 1200000000.
    """
    for fact in facts:
        if fact.value == 0:
            continue
        for scale in SCALE_CANDIDATES:
            scaled = value * scale
            if abs(scaled - fact.value) / abs(fact.value) < MATCH_TOLERANCE:
                return fact
    return None


def extract_prose_pairs(
    document_id: str,
    page_blocks: list[list[str]],
    facts: list[Fact],
    located: dict[str, Span],
    tagged_displayed: set[str] | None = None,
) -> list[ProsePair]:
    """Find narrative figures that resolve to a located tagged fact.

    ``page_blocks`` holds the layout blocks of the *unstamped* rendering, one
    list per page. Blocks rather than whole-page text, deliberately: a page dump
    concatenates headers, tables and paragraphs into a single string, and
    sentence splitting on that produces blobs that pass a prose check while
    being nothing of the kind. Layout blocks keep a paragraph a paragraph.
    """
    from disclosure_rag.labels.facts import normalise_number

    by_id = {fact.fact_id: fact for fact in facts}
    pairs: list[ProsePair] = []

    for page_number, blocks in enumerate(page_blocks):
        for block in blocks:
            if not is_prose(block):
                continue  # the block itself must read as prose, not just a slice of it
            for match in NUMBER.finditer(block):
                written = match.group()
                if not is_specific(written):
                    continue
                if tagged_displayed and written in tagged_displayed:
                    # Appears verbatim as a tagged value, so this is very likely
                    # the statement itself, not a narrative restatement of it.
                    continue
                value = normalise_number(written)
                if value is None or abs(value) < 100:
                    continue  # note references and page numbers
                sentence = sentence_around(block, match.start())
                if not is_prose(sentence):
                    continue
                fact = resolve_to_fact(value, facts)
                if fact is None or fact.fact_id not in located:
                    continue
                pairs.append(
                    ProsePair(
                        document_id=document_id,
                        sentence=" ".join(sentence.split())[:400],
                        mention=written,
                        page=page_number,
                        fact_id=fact.fact_id,
                        concept=by_id[fact.fact_id].concept,
                        value=fact.value,
                        gold_span=located[fact.fact_id],
                    )
                )
    return pairs


def build(
    document_id: str,
    facts: list[Fact],
    located: dict[str, Span],
    page_blocks: list[list[str]] | None = None,
    confirmation: Confirmation | None = None,
) -> FactLedger:
    """Join extracted facts with their locations into a ledger."""
    rows = [
        LocatedFact(fact=fact, span=located[fact.fact_id])
        for fact in facts
        if fact.fact_id in located
    ]
    pairs: list[ProsePair] = []
    if page_blocks:
        tagged = {fact.displayed for fact in facts}
        pairs = extract_prose_pairs(document_id, page_blocks, facts, located, tagged)
    return FactLedger(
        document_id=document_id,
        facts=rows,
        prose_pairs=pairs,
        coverage=len(rows) / len(facts) if facts else 0.0,
        confirmation=confirmation or Confirmation(),
    )


def write_review_csv(ledgers: list[FactLedger], path: Path) -> int:
    """Write prose-pair candidates for hand review.

    The same discipline the M0 probe used: an automated pass narrows the field
    and a person decides. Filling in the ``confirmed`` column is what turns a
    candidate into a label.
    """
    import csv

    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "confirmed": "",  # y or n, filled in by hand
            "document_id": pair.document_id,
            "mention": pair.mention,
            "concept": pair.concept,
            "value": str(pair.value),
            "page": pair.page,
            "fact_id": pair.fact_id,
            "sentence": pair.sentence,
        }
        for ledger in ledgers
        for pair in ledger.prose_pairs
    ]
    if not rows:
        return 0
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def write_index(ledgers: list[FactLedger], path: Path) -> None:
    """A small summary across documents, for the corpus README and for CI."""
    path.parent.mkdir(parents=True, exist_ok=True)
    summary: dict[str, object] = {
        "documents": len(ledgers),
        "facts": sum(len(item.facts) for item in ledgers),
        "prose_pairs": sum(len(item.prose_pairs) for item in ledgers),
        "per_document": [
            {
                "document_id": item.document_id,
                "facts": len(item.facts),
                "prose_pairs": len(item.prose_pairs),
                "coverage": item.coverage,
                "confirmation": item.confirmation.model_dump(),
            }
            for item in ledgers
        ],
    }
    path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
