"""Stage 5: write REPORT.md, comparing what was measured against the thresholds.

The verdict is mechanical. The thresholds were written down before the probe
ran, so this stage only applies them, which is the point: it removes the chance
to reinterpret a disappointing result as a pass.
"""

from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

from . import (
    GEOMETRY_REPORT,
    MIN_GEOMETRY_CONFIRMED_RATE,
    MIN_GEOMETRY_MEDIAN_IOU,
    MIN_NARRATIVE_RESOLVED,
    NARRATIVE_REPORT,
    NARRATIVE_REVIEW,
    NARRATIVE_SAMPLE_SIZE,
)

OUT = Path(__file__).parent / "REPORT.md"


def _confirmed_count() -> int | None:
    """Prefer the hand-confirmed count over the generous automated one."""
    if not NARRATIVE_REVIEW.exists():
        return None
    with NARRATIVE_REVIEW.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    marked = [r for r in rows if (r.get("confirmed") or "").strip().lower() in {"y", "n"}]
    if not marked:
        return None
    return sum(1 for r in marked if r["confirmed"].strip().lower() == "y")


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def run() -> None:
    geometry = _load(GEOMETRY_REPORT)
    narrative = _load(NARRATIVE_REPORT)
    confirmed = _confirmed_count()

    resolved = confirmed if confirmed is not None else narrative.get("auto_resolved")
    basis = "hand-confirmed" if confirmed is not None else "automated, not yet confirmed"

    a1_pass = resolved is not None and resolved >= MIN_NARRATIVE_RESOLVED
    rate = geometry.get("confirmed_rate")
    iou = geometry.get("median_iou")
    a2_pass = (
        rate is not None
        and iou is not None
        and rate >= MIN_GEOMETRY_CONFIRMED_RATE
        and iou >= MIN_GEOMETRY_MEDIAN_IOU
    )

    def mark(ok: bool, have: object) -> str:
        if have is None:
            return "not measured"
        return "PASS" if ok else "FAIL"

    lines = [
        "# M0 probe: results",
        "",
        f"Run on {date.today().isoformat()}. Thresholds were fixed in "
        "[README.md](README.md) before the probe ran; this file only applies them.",
        "",
        "## Verdict",
        "",
        "| Assumption | Threshold | Measured | Result |",
        "|---|---|---|---|",
        f"| A1 narrative figures resolve to tagged facts | {MIN_NARRATIVE_RESOLVED} "
        f"of {NARRATIVE_SAMPLE_SIZE} | {resolved if resolved is not None else 'not measured'} "
        f"({basis}) | {mark(a1_pass, resolved)} |",
        f"| A2 browser boxes confirmed on the printed page | "
        f"{MIN_GEOMETRY_CONFIRMED_RATE:.0%} | "
        f"{f'{rate:.1%}' if rate is not None else 'not measured'} | {mark(a2_pass, rate)} |",
        f"| A2 median IoU against the PDF | {MIN_GEOMETRY_MEDIAN_IOU} | "
        f"{f'{iou:.3f}' if iou is not None else 'not measured'} | {mark(a2_pass, iou)} |",
        "",
        "## What follows from this",
        "",
    ]

    if resolved is None or rate is None:
        lines.append(
            "Not enough measured yet to decide. Run the remaining stages, then confirm the "
            "sampled rows in `work/narrative_review.csv` by hand before trusting the A1 number."
        )
    else:
        lines.append(
            "- **M4 reconciliation proceeds.**" if a1_pass else
            "- **M4 reconciliation is cut.** Narrative prose does not restate enough tagged "
            "figures for the oracle to supply free labels. The project becomes disclosure "
            "location only, and the README says so."
        )
        lines.append(
            "- **Region-level citations proceed**, and citation IoU stays as the headline metric."
            if a2_pass else
            "- **Citations drop to page level.** Browser geometry does not map onto the printed "
            "page reliably enough. The IoU metric is removed rather than reported at a precision "
            "the measurement does not support."
        )

    lines += [
        "",
        "## Notes",
        "",
        "- The automated resolution pass is generous by design: it counts a match when an "
        "unrelated number happens to equal a fact. The number above is only trustworthy once "
        "the `confirmed` column in `work/narrative_review.csv` is filled in.",
        "- Per-filing detail is in `work/geometry_check.json` and `work/narrative_check.json`.",
        "",
        "## Raw",
        "",
        "```json",
        json.dumps({"geometry": geometry, "narrative": narrative}, indent=2),
        "```",
        "",
    ]

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"[report] wrote {OUT}")
