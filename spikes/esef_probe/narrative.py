"""Stage 4: measure assumption A1, that narrative prose restates tagged figures.

Takes numbers that appear in the rendered document but *outside* any tagged
element, and asks whether each one resolves to a fact in the ledger. That is the
task the reconciliation feature would have to perform, so the resolvable share
is a direct estimate of whether the feature has free labels available.

Two resolution paths are counted, matching the abort criterion:

- exact, where the narrative figure restates a tagged value at the precision the
  narrative itself uses ("roughly 1.2 billion" restates 1,204,000,000)
- derived in one step, where it is a ratio or a period-over-period change
  between two facts of the same concept

Anything else counts as unresolvable.

The matching here is deliberately generous, so it overcounts: an unrelated
number that happens to equal a fact will be scored as a match. That is why the
stage writes a review CSV. The automated pass narrows the field and the number
that goes in the report is the one confirmed by hand.
"""

from __future__ import annotations

import csv
import json
import random
import re
from decimal import Decimal
from pathlib import Path

import fitz  # PyMuPDF

from . import (
    LEDGER,
    NARRATIVE_REPORT,
    NARRATIVE_REVIEW,
    NARRATIVE_SAMPLE_SIZE,
    RENDERS,
    ensure_dirs,
)
from .facts import normalise_number

NUMBER = re.compile(r"(?<![\w.,])-?\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?(?![\w])")
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
WORD = re.compile(r"[^\W\d_]{3,}", re.UNICODE)
SEED = 20260729  # fixed so a rerun samples the same items

# A1 is a claim about narrative prose, so the denominator has to be prose. The
# first version of this stage sampled every untagged number in the document,
# which pulled in untagged table grids, the table of contents, page footers and
# the sustainability section. Those are not sentences and nobody would expect
# them to restate a tagged fact, so including them measured the wrong thing.
MIN_SENTENCE_CHARS = 60
MIN_SENTENCE_WORDS = 8
MAX_DIGIT_RATIO = 0.20


def _sentence_around(text: str, position: int) -> str:
    """The sentence containing a match, so prose can be told from a table row."""
    start = 0
    for piece in SENTENCE_SPLIT.split(text):
        end = start + len(piece)
        if start <= position <= end:
            return piece.strip()
        start = end + 1
    return text.strip()


def _is_prose(sentence: str) -> bool:
    """True for something a person wrote as a sentence, false for a table row.

    Three cheap signals together: long enough to be a sentence, enough real
    words in it, and not mostly digits. A row like "Gesamt 197.315 737.935
    4.230.415" fails the second and third; a sentence like "Die Position
    Kassenbestand ist um EUR 136,3 Mio. gestiegen" passes all three.
    """
    if len(sentence) < MIN_SENTENCE_CHARS:
        return False
    if len(WORD.findall(sentence)) < MIN_SENTENCE_WORDS:
        return False
    digits = sum(character.isdigit() for character in sentence)
    return digits / len(sentence) < MAX_DIGIT_RATIO


def _tagged_boxes(name: str) -> dict[int, list[list[float]]]:
    """Tagged regions per page, so this stage can exclude them.

    The geometry stage writes a mapping of probe id to location, so the values
    are what matter here rather than the keys.
    """
    path = RENDERS / f"{name}.boxes.json"
    if not path.exists():
        return {}
    by_page: dict[int, list[list[float]]] = {}
    for location in json.loads(path.read_text(encoding="utf-8")).values():
        by_page.setdefault(location["page"], []).append(location["bbox"])
    return by_page


def _inside(point: tuple[float, float], boxes: list[list[float]]) -> bool:
    x, y = point
    return any(x0 <= x <= x1 and y0 <= y <= y1 for x0, y0, x1, y1 in boxes)


def _candidates(pdf_path: Path, tagged: dict[int, list[list[float]]]) -> list[dict]:
    """Numeric mentions on the page that do not sit inside a tagged element."""
    document = fitz.open(pdf_path)
    found: list[dict] = []
    for page_index in range(document.page_count):
        page = document[page_index]
        width, height = page.rect.width, page.rect.height
        boxes = tagged.get(page_index, [])
        for block in page.get_text("blocks"):
            x0, y0, x1, y1, text = block[0], block[1], block[2], block[3], block[4]
            centre = ((x0 + x1) / 2 / width, (y0 + y1) / 2 / height)
            if _inside(centre, boxes):
                continue
            for match in NUMBER.finditer(text):
                value = normalise_number(match.group())
                if value is None or abs(value) < 100:
                    continue  # tiny numbers are note references and page numbers
                sentence = _sentence_around(text, match.start())
                found.append(
                    {
                        "page": page_index,
                        "mention": match.group(),
                        "value": str(value),
                        "is_prose": _is_prose(sentence),
                        "context": " ".join(sentence.split())[:220],
                    }
                )
    document.close()
    return found


def _exact_match(value: Decimal, facts: list[dict]) -> dict | None:
    """A narrative figure restates a fact if it agrees at its own precision."""
    for fact in facts:
        fact_value = Decimal(fact["value"])
        if fact_value == 0:
            continue
        if value == fact_value:
            return fact
        # "roughly 1.2 billion" against 1,204,000,000: agree at the narrative's
        # precision, which is the tolerance policy the real system would apply.
        for scale in (Decimal(1), Decimal(1_000), Decimal(1_000_000), Decimal(1_000_000_000)):
            scaled = value * scale
            if fact_value != 0 and abs(scaled - fact_value) / abs(fact_value) < Decimal("0.005"):
                return fact
    return None


def _derived_match(value: Decimal, facts: list[dict]) -> dict | None:
    """A percentage change between two facts of the same concept."""
    if not (Decimal("-100") < value < Decimal("1000")):
        return None
    by_concept: dict[str, list[dict]] = {}
    for fact in facts:
        by_concept.setdefault(fact["concept"], []).append(fact)
    for concept, group in by_concept.items():
        if len(group) < 2:
            continue
        for a in group[:6]:
            for b in group[:6]:
                first, second = Decimal(a["value"]), Decimal(b["value"])
                if first == 0 or a is b:
                    continue
                change = (second - first) / abs(first) * 100
                if abs(change - value) < Decimal("0.5"):
                    return {"concept": concept, "value": f"derived: {change:.2f}%"}
    return None


def run() -> dict:
    ensure_dirs()
    if not LEDGER.exists():
        print("[narrative] no ledger, run the facts stage first")
        return {}

    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    pool: list[dict] = []
    for name in ledger:
        pdf_path = RENDERS / f"{name}.pdf"
        if not pdf_path.exists():
            continue
        for candidate in _candidates(pdf_path, _tagged_boxes(name)):
            pool.append(candidate | {"filing": name})

    if not pool:
        print("[narrative] no untagged numeric mentions found, run the geometry stage first")
        return {}

    prose = [item for item in pool if item["is_prose"]]
    print(
        f"[narrative] {len(pool)} untagged numeric mentions, "
        f"{len(prose)} of them in prose sentences ({len(prose) / len(pool):.1%})"
    )
    if not prose:
        print("[narrative] no prose mentions found, cannot measure A1")
        return {}

    random.Random(SEED).shuffle(prose)
    sample = prose[:NARRATIVE_SAMPLE_SIZE]

    rows: list[dict] = []
    counts = {"exact": 0, "derived": 0, "unresolved": 0}
    for item in sample:
        facts = ledger[item["filing"]]
        value = Decimal(item["value"])
        match = _exact_match(value, facts)
        kind = "exact"
        if match is None:
            match = _derived_match(value, facts)
            kind = "derived" if match else "unresolved"
        counts[kind] += 1
        rows.append(
            item
            | {
                "auto_class": kind,
                "matched_concept": (match or {}).get("concept", ""),
                "matched_value": (match or {}).get("value", ""),
                "confirmed": "",  # filled in by hand: y or n
            }
        )

    with NARRATIVE_REVIEW.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    resolved = counts["exact"] + counts["derived"]
    summary = {
        "sampled": len(sample),
        "auto_resolved": resolved,
        "breakdown": counts,
        "pool_all_untagged": len(pool),
        "pool_prose": len(prose),
        "review_file": str(NARRATIVE_REVIEW),
        "note": "auto_resolved overcounts. Confirm rows in the CSV and use the confirmed count.",
    }
    NARRATIVE_REPORT.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"[narrative] {resolved}/{len(sample)} auto-resolved, review {NARRATIVE_REVIEW}")
    return summary
