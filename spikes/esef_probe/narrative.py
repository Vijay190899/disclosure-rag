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
SEED = 20260729  # fixed so a rerun samples the same items


def _tagged_boxes(name: str) -> dict[int, list[list[float]]]:
    path = RENDERS / f"{name}.boxes.json"
    if not path.exists():
        return {}
    by_page: dict[int, list[list[float]]] = {}
    for box in json.loads(path.read_text(encoding="utf-8")):
        by_page.setdefault(box["page"], []).append(box["bbox"])
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
                start = max(0, match.start() - 90)
                found.append(
                    {
                        "page": page_index,
                        "mention": match.group(),
                        "value": str(value),
                        "context": " ".join(text[start : match.end() + 60].split()),
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

    random.Random(SEED).shuffle(pool)
    sample = pool[:NARRATIVE_SAMPLE_SIZE]

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
        "review_file": str(NARRATIVE_REVIEW),
        "note": "auto_resolved overcounts. Confirm rows in the CSV and use the confirmed count.",
    }
    NARRATIVE_REPORT.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"[narrative] {resolved}/{len(sample)} auto-resolved, review {NARRATIVE_REVIEW}")
    return summary
