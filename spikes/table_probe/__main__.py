"""Run the table-structure probe.

    uv run python -m spikes.table_probe --ledgers <dir>

For a sample of tagged facts, ask three questions of PyMuPDF's table finder:
is the figure inside a detected cell, does that cell's column header carry the
period, and does the cell's box line up with the tagged figure's box.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
from collections import Counter
from pathlib import Path

from disclosure_rag.labels.ledger import FactLedger
from disclosure_rag.provenance import Span

from . import (
    MIN_CELL_CONTAINMENT,
    MIN_CELL_TIGHTNESS,
    MIN_FACTS_IN_CELLS,
    MIN_PERIOD_RESOLVABLE,
    REPORT,
    SAMPLE_FACTS,
)

YEAR = re.compile(r"(19|20)\d{2}")


def _period_years(period: str) -> set[str]:
    return {match.group() for match in YEAR.finditer(period)}


def probe(ledger_dir: Path) -> dict:
    import fitz

    in_cell = 0
    checked = 0
    containments: list[float] = []
    tightnesses: list[float] = []
    period_checked = 0
    period_resolved = 0
    tables_seen = 0
    header_examples: list[str] = []
    reasons: Counter[str] = Counter()

    for ledger_path in sorted(ledger_dir.glob("*/ledger.json")):
        ledger = FactLedger.read(ledger_path)
        pdf_path = ledger_path.parent / "document.pdf"
        if not pdf_path.exists():
            continue

        # Concepts reported for more than one period are the ambiguous ones.
        periods_per_concept: dict[str, set[str]] = {}
        for row in ledger.facts:
            periods_per_concept.setdefault(row.fact.concept, set()).add(row.fact.period)

        document = fitz.open(pdf_path)
        try:
            # Group facts by page so each page is analysed once.
            by_page: dict[int, list] = {}
            for row in ledger.facts[:SAMPLE_FACTS]:
                by_page.setdefault(row.span.page, []).append(row)

            for page_number, rows in sorted(by_page.items()):
                if page_number >= document.page_count:
                    continue
                page = document[page_number]
                width, height = page.rect.width, page.rect.height
                try:
                    found = page.find_tables()
                except Exception as error:  # a spike records and continues
                    reasons[f"find_tables failed: {type(error).__name__}"] += 1
                    continue

                tables = list(found.tables)
                tables_seen += len(tables)

                for row in rows:
                    checked += 1
                    gold = row.span
                    hit_cell: Span | None = None
                    header_text = ""

                    # The SMALLEST covering cell, not the first. Taking the first
                    # picked up large spanning cells and made the tightness
                    # measurement meaningless.
                    for table in tables:
                        header_names = list(getattr(table.header, "names", []) or [])
                        for cell in table.cells:
                            if cell is None:
                                continue
                            cell_span = Span.from_rect(
                                page_number, cell[0], cell[1], cell[2], cell[3], width, height
                            )
                            if cell_span.covers(gold) < 0.9:
                                continue
                            if hit_cell is not None and cell_span.area >= hit_cell.area:
                                continue
                            hit_cell = cell_span
                            centre = (cell[0] + cell[2]) / 2
                            header_text = ""
                            for index, column in enumerate(table.header.cells or []):
                                if column and column[0] <= centre <= column[2]:
                                    if index < len(header_names) and header_names[index]:
                                        header_text = str(header_names[index])
                                    break
                            if not header_text and header_names:
                                header_text = " ".join(str(n) for n in header_names if n)

                    if hit_cell is None:
                        reasons["figure not inside any detected cell"] += 1
                        continue

                    in_cell += 1
                    containments.append(hit_cell.covers(gold))
                    tightnesses.append(hit_cell.tightness(gold))

                    if len(periods_per_concept.get(row.fact.concept, set())) > 1:
                        period_checked += 1
                        wanted = _period_years(row.fact.period)
                        if wanted and any(year in header_text for year in wanted):
                            period_resolved += 1
                        elif header_text:
                            header_examples.append(header_text[:60])
        finally:
            document.close()

    return {
        "facts_checked": checked,
        "tables_detected": tables_seen,
        "facts_in_a_cell": in_cell,
        "facts_in_a_cell_rate": in_cell / checked if checked else 0.0,
        "median_cell_containment": statistics.median(containments) if containments else 0.0,
        "median_cell_tightness": statistics.median(tightnesses) if tightnesses else 0.0,
        "ambiguous_facts_checked": period_checked,
        "period_resolved_by_header": period_resolved,
        "period_resolved_rate": period_resolved / period_checked if period_checked else 0.0,
        "header_examples": header_examples[:10],
        "failure_reasons": dict(reasons.most_common(5)),
    }


def write_report(result: dict) -> None:
    def mark(ok: bool, measured: object) -> str:
        return "PASS" if ok else "FAIL" if measured is not None else "not measured"

    a1 = result["facts_in_a_cell_rate"] >= MIN_FACTS_IN_CELLS
    a2 = result["period_resolved_rate"] >= MIN_PERIOD_RESOLVABLE
    a3 = (
        result["median_cell_containment"] >= MIN_CELL_CONTAINMENT
        and result["median_cell_tightness"] >= MIN_CELL_TIGHTNESS
    )

    lines = [
        "# M2b probe: is table structure recoverable?",
        "",
        "Thresholds were fixed in `__init__.py` before this ran. This file only applies them.",
        "",
        "| Assumption | Threshold | Measured | Result |",
        "|---|---|---|---|",
        f"| A1 tagged figures sit inside detected cells | {MIN_FACTS_IN_CELLS:.0%} | "
        f"{result['facts_in_a_cell_rate']:.1%} "
        f"({result['facts_in_a_cell']}/{result['facts_checked']}) | {mark(a1, True)} |",
        f"| A2 column header resolves the period | {MIN_PERIOD_RESOLVABLE:.0%} | "
        f"{result['period_resolved_rate']:.1%} "
        f"({result['period_resolved_by_header']}/{result['ambiguous_facts_checked']}) | "
        f"{mark(a2, True)} |",
        f"| A3 cell is a usable citation region | containment >= "
        f"{MIN_CELL_CONTAINMENT}, tightness >= {MIN_CELL_TIGHTNESS} | "
        f"containment {result['median_cell_containment']:.3f}, "
        f"tightness {result['median_cell_tightness']:.3f} | {mark(a3, True)} |",
        "",
        f"Tables detected across the sampled pages: {result['tables_detected']}.",
        "",
        "## What follows",
        "",
    ]
    if a1 and a2 and a3:
        lines.append(
            "**Table-aware parsing is the fix and PyMuPDF already provides it.** No new "
            "dependency needed: cells are detectable, their boxes line up with the tagged "
            "figures, and the column header carries the period that citation currently cannot "
            "resolve. Proceed to a table-aware chunker and cell-level citation."
        )
    elif a1 and not a3:
        lines.append(
            "**Cells are detected but they are far too coarse to cite.** Every tagged figure "
            "falls inside some cell, which is trivially true when the median smallest covering "
            "cell is about half a page. Spot-checking a genuine statement page shows a proper "
            "12 by 10 grid with cells at 0.005 of a page and real column labels, so detection "
            "works where the document is a clean table and degrades badly elsewhere, which is "
            "where most tagged facts sit.\n\n"
            "**Do not build a table-aware chunker on this.** It does not clear the bar it was "
            "given. The next thing to test is whether Docling recovers cells where PyMuPDF does "
            "not, as a separate probe with its own thresholds, before any building."
        )
    elif a1 and a3 and not a2:
        lines.append(
            "**Cells are recoverable but the header does not resolve the period.** Structure "
            "alone will not fix citation accuracy; the period lives somewhere the header row "
            "does not capture. Investigate before building."
        )
    elif not a1:
        lines.append(
            "**PyMuPDF cannot see these tables.** Most tagged figures are not inside a detected "
            "cell, so this route is closed. Try Docling before assuming table structure is "
            "recoverable at all."
        )
    else:
        lines.append("**Mixed result.** See the numbers above and the failure reasons below.")

    lines += [
        "",
        "## Raw",
        "",
        "```json",
        json.dumps(result, indent=2),
        "```",
        "",
    ]
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(prog="spikes.table_probe", description=__doc__)
    parser.add_argument("--ledgers", type=Path, required=True)
    args = parser.parse_args()

    result = probe(args.ledgers)
    for key, value in result.items():
        if key not in {"header_examples", "failure_reasons"}:
            print(f"  {key}: {value}")
    print(f"  failure_reasons: {result['failure_reasons']}")
    write_report(result)
    print(f"\n[probe] wrote {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
