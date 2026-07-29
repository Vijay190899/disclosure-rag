"""Stage 3: measure assumption A2, that browser geometry maps onto the printed page.

Renders the stamped report in headless Chromium, reads a bounding box for every
tagged fact, and prints the same pass to PDF. Then it checks its own work:
PyMuPDF searches the predicted page for the fact's displayed text and the two
boxes are compared.

That verification step is the whole point. Without it this stage would report
where the browser thinks a number is, which is the claim under test rather than
evidence for it.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

import fitz  # PyMuPDF
from playwright.sync_api import sync_playwright

from . import FILINGS, GEOMETRY_REPORT, RENDERS, ensure_dirs
from .facts import PROBE_ID_ATTR

# A4 at 96 CSS pixels per inch. Page index is derived arithmetically from the
# vertical offset, which ignores real page breaks. The verification step below
# is what measures how much that approximation costs.
PAGE_W_PX = 794
PAGE_H_PX = 1123

COLLECT_BOXES = f"""
() => {{
  const out = [];
  document.querySelectorAll('[{PROBE_ID_ATTR}]').forEach(el => {{
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) return;
    out.push({{
      probe_id: el.getAttribute('{PROBE_ID_ATTR}'),
      text: (el.textContent || '').trim(),
      x: r.left + window.scrollX,
      y: r.top + window.scrollY,
      w: r.width,
      h: r.height,
    }});
  }});
  return out;
}}
"""


def _to_page_box(raw: dict) -> dict:
    """Convert a document-space CSS box into a page index and a normalised box."""
    page = int(raw["y"] // PAGE_H_PX)
    y_on_page = raw["y"] - page * PAGE_H_PX
    return {
        "probe_id": raw["probe_id"],
        "text": raw["text"],
        "page": page,
        "bbox": [
            raw["x"] / PAGE_W_PX,
            y_on_page / PAGE_H_PX,
            (raw["x"] + raw["w"]) / PAGE_W_PX,
            (y_on_page + raw["h"]) / PAGE_H_PX,
        ],
    }


def capture(report: Path, pdf_out: Path) -> list[dict]:
    with sync_playwright() as play:
        browser = play.chromium.launch()
        page = browser.new_page(viewport={"width": PAGE_W_PX, "height": PAGE_H_PX})
        page.goto(report.resolve().as_uri(), wait_until="networkidle")
        raw = page.evaluate(COLLECT_BOXES)
        # Same pass, so the coordinate space is shared between boxes and PDF.
        page.pdf(
            path=str(pdf_out),
            width=f"{PAGE_W_PX}px",
            height=f"{PAGE_H_PX}px",
            print_background=True,
            margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
        )
        browser.close()
    return [_to_page_box(item) for item in raw]


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


def verify(pdf_path: Path, predictions: list[dict], sample: int = 200) -> dict:
    """Search the PDF for each fact's text and compare boxes with the prediction."""
    document = fitz.open(pdf_path)
    confirmed = 0
    checked = 0
    ious: list[float] = []

    for prediction in predictions[:sample]:
        text = prediction["text"]
        if not text or prediction["page"] >= document.page_count:
            continue
        checked += 1
        page = document[prediction["page"]]
        hits = page.search_for(text)
        if not hits:
            continue
        width, height = page.rect.width, page.rect.height
        best = max(
            (
                _iou(prediction["bbox"], [h.x0 / width, h.y0 / height, h.x1 / width, h.y1 / height])
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
    results: dict[str, dict] = {}

    for stamped in sorted(FILINGS.glob("*/report.stamped.xhtml")):
        name = stamped.parent.name
        pdf_out = RENDERS / f"{name}.pdf"
        print(f"[geometry] rendering {name}")
        predictions = capture(stamped, pdf_out)
        print(f"[geometry] {len(predictions)} boxes, verifying against {pdf_out.name}")
        results[name] = verify(pdf_out, predictions) | {"boxes": len(predictions)}
        (RENDERS / f"{name}.boxes.json").write_text(
            json.dumps(predictions, indent=2), encoding="utf-8"
        )
        print(f"[geometry] {name}: {results[name]}")

    if not results:
        print("[geometry] no stamped reports found, run the facts stage first")

    checked = sum(r["checked"] for r in results.values())
    confirmed = sum(r["confirmed"] for r in results.values())
    medians = [r["median_iou"] for r in results.values() if r["median_iou"]]
    summary = {
        "per_filing": results,
        "checked": checked,
        "confirmed": confirmed,
        "confirmed_rate": confirmed / checked if checked else 0.0,
        "median_iou": statistics.median(medians) if medians else 0.0,
    }
    GEOMETRY_REPORT.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary
