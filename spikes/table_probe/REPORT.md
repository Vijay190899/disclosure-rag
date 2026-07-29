# M2b probe: is table structure recoverable?

Thresholds were fixed in `__init__.py` before this ran. This file only applies them.

| Assumption | Threshold | Measured | Result |
|---|---|---|---|
| A1 tagged figures sit inside detected cells | 60% | 100.0% (600/600) | PASS |
| A2 column header resolves the period | 50% | 38.5% (218/566) | FAIL |
| A3 cell is a usable citation region | containment >= 0.9, tightness >= 0.02 | containment 1.000, tightness 0.001 | FAIL |

Tables detected across the sampled pages: 23.

## What follows

**Cells are detected but they are far too coarse to cite.** Every tagged figure falls inside some cell, which is trivially true when the median smallest covering cell is about half a page. Spot-checking a genuine statement page shows a proper 12 by 10 grid with cells at 0.005 of a page and real column labels, so detection works where the document is a clean table and degrades badly elsewhere, which is where most tagged facts sit.

**Do not build a table-aware chunker on this.** It does not clear the bar it was given. The next thing to test is whether Docling recovers cells where PyMuPDF does not, as a separate probe with its own thresholds, before any building.

## Raw

```json
{
  "facts_checked": 600,
  "tables_detected": 23,
  "facts_in_a_cell": 600,
  "facts_in_a_cell_rate": 1.0,
  "median_cell_containment": 1.0,
  "median_cell_tightness": 0.000528397435826515,
  "ambiguous_facts_checked": 566,
  "period_resolved_by_header": 218,
  "period_resolved_rate": 0.38515901060070673,
  "header_examples": [
    "Erfolgsrechnung",
    "Erfolgsrechnung",
    "Erfolgsrechnung",
    "Erfolgsrechnung",
    "Erfolgsrechnung",
    "Erfolgsrechnung",
    "Erfolgsrechnung",
    "Erfolgsrechnung",
    "Erfolgsrechnung",
    "Erfolgsrechnung"
  ],
  "failure_reasons": {}
}
```
