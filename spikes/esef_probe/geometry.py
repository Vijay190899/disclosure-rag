"""Stage 3: measure assumption A2, that tagged facts can be located on the printed page.

Renders the stamped report to PDF with Chromium and reads back the link
annotations. Each tagged fact was wrapped in an anchor by the facts stage, and
Chromium preserves anchors as PDF link annotations carrying the page number and
a rectangle in PDF coordinate space. That is the location, taken from the
printed artefact itself.

**This replaced an approach that did not work.** The first version read
getBoundingClientRect in the browser and derived a page index by dividing the
vertical offset by a fixed page height. It located 0 of 600 facts. Screen layout
and print layout are different layouts: Chromium repaginates when printing, so
the scroll offset of an element says nothing about which printed page it lands
on. On one filing the arithmetic predicted pages 22 to 67 for a document that
printed to 184 pages.

Link annotations do not have that problem, because they are produced by the same
pagination pass that produces the pages.

Verification is still independent: PyMuPDF searches the annotated page for the
fact's displayed text and the two rectangles are compared. The link says where
the fact is, the text search says where that text actually is, and the IoU
between them is the measurement.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

import fitz  # PyMuPDF
from playwright.sync_api import sync_playwright

from . import FILINGS, GEOMETRY_REPORT, RENDERS, ensure_dirs
from .facts import PROBE_URI


def render(report: Path, pdf_out: Path) -> None:
    with sync_playwright() as play:
        browser = play.chromium.launch()
        page = browser.new_page()
        page.goto(report.resolve().as_uri(), wait_until="load")
        page.pdf(path=str(pdf_out), format="A4", print_background=True)
        browser.close()


def locate(pdf_path: Path) -> dict[str, dict]:
    """Read one page and rectangle per tagged fact out of the PDF link annotations."""
    document = fitz.open(pdf_path)
    located: dict[str, dict] = {}
    for page_number in range(document.page_count):
        page = document[page_number]
        width, height = page.rect.width, page.rect.height
        for link in page.get_links():
            uri = link.get("uri") or ""
            if PROBE_URI not in uri:
                continue
            probe_id = uri.rsplit("/", 1)[-1]
            if probe_id in located:
                continue  # first occurrence wins
            rect = link["from"]
            located[probe_id] = {
                "page": page_number,
                "bbox": [
                    rect.x0 / width,
                    rect.y0 / height,
                    rect.x1 / width,
                    rect.y1 / height,
                ],
            }
    document.close()
    return located


def _iou(a: list[float], b: list[float]) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    intersection = (ix1 - ix0) * (iy1 - iy0)
    union = (ax1 - ax0) * (ay1 - ay0) + (bx1 - bx0) * (by1 - by0) - intersection
    return intersection / union if union > 0 else 0.0


def verify(pdf_path: Path, located: dict[str, dict], facts: list[dict], sample: int = 200) -> dict:
    """Independently check each located box by searching the page for its text."""
    document = fitz.open(pdf_path)
    by_id = {fact["probe_id"]: fact for fact in facts}
    checked = 0
    confirmed = 0
    ious: list[float] = []

    for probe_id, location in list(located.items())[:sample]:
        fact = by_id.get(probe_id)
        if not fact or not fact["displayed"]:
            continue
        checked += 1
        page = document[location["page"]]
        hits = page.search_for(fact["displayed"])
        if not hits:
            continue
        width, height = page.rect.width, page.rect.height
        best = max(
            (
                _iou(
                    location["bbox"],
                    [h.x0 / width, h.y0 / height, h.x1 / width, h.y1 / height],
                )
                for h in hits
            ),
            default=0.0,
        )
        if best > 0:
            confirmed += 1
            ious.append(best)

    document.close()
    return {
        "checked": checked,
        "confirmed": confirmed,
        "confirmed_rate": confirmed / checked if checked else 0.0,
        "median_iou": statistics.median(ious) if ious else 0.0,
    }


def run() -> dict:
    ensure_dirs()
    ledger_path = RENDERS.parent / "ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.exists() else {}
    results: dict[str, dict] = {}

    for stamped in sorted(FILINGS.glob("*/report.stamped.xhtml")):
        name = stamped.parent.name
        facts = ledger.get(name, [])
        pdf_out = RENDERS / f"{name}.pdf"
        print(f"[geometry] rendering {name}")
        render(stamped, pdf_out)

        located = locate(pdf_out)
        coverage = len(located) / len(facts) if facts else 0.0
        print(f"[geometry] located {len(located)}/{len(facts)} facts ({coverage:.1%})")

        results[name] = verify(pdf_out, located, facts) | {
            "facts": len(facts),
            "located": len(located),
            "coverage": coverage,
        }
        (RENDERS / f"{name}.boxes.json").write_text(json.dumps(located, indent=2), encoding="utf-8")
        print(f"[geometry] {name}: {results[name]}")

    if not results:
        print("[geometry] no stamped reports found, run the facts stage first")

    checked = sum(r["checked"] for r in results.values())
    confirmed = sum(r["confirmed"] for r in results.values())
    facts_total = sum(r["facts"] for r in results.values())
    located_total = sum(r["located"] for r in results.values())
    medians = [r["median_iou"] for r in results.values() if r["median_iou"]]
    summary = {
        "per_filing": results,
        "facts": facts_total,
        "located": located_total,
        "coverage": located_total / facts_total if facts_total else 0.0,
        "checked": checked,
        "confirmed": confirmed,
        "confirmed_rate": confirmed / checked if checked else 0.0,
        "median_iou": statistics.median(medians) if medians else 0.0,
    }
    GEOMETRY_REPORT.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary
