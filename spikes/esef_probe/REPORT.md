# M0 probe: results

Run on 2026-07-29. Thresholds were fixed in [README.md](README.md) before the probe ran; this file only applies them.

## Verdict

| Assumption | Threshold | Measured | Result |
|---|---|---|---|
| A1 narrative figures resolve to tagged facts | 20 of 50 | 19 (automated, not yet confirmed) | FAIL |
| A2 browser boxes confirmed on the printed page | 90% | 100.0% | PASS |
| A2 median IoU against the PDF | 0.5 | 0.947 | PASS |

## What follows from this

- **M4 reconciliation is cut.** Narrative prose does not restate enough tagged figures for the oracle to supply free labels. The project becomes disclosure location only, and the README says so.
- **Region-level citations proceed**, and citation IoU stays as the headline metric.

## Notes

- The automated resolution pass is generous by design: it counts a match when an unrelated number happens to equal a fact. The number above is only trustworthy once the `confirmed` column in `work/narrative_review.csv` is filled in.
- Per-filing detail is in `work/geometry_check.json` and `work/narrative_check.json`.

## Raw

```json
{
  "geometry": {
    "per_filing": {
      "529900JNA1MSNDLJVC46-2022-12-31-ESEF-AT-1": {
        "checked": 200,
        "confirmed": 200,
        "confirmed_rate": 1.0,
        "median_iou": 0.9784182464520423,
        "facts": 234,
        "located": 234,
        "coverage": 1.0
      },
      "529900UKZBMDBDZIXD62-2022-12-31-ESEF-AT-0": {
        "checked": 200,
        "confirmed": 200,
        "confirmed_rate": 1.0,
        "median_iou": 0.9236259684040362,
        "facts": 366,
        "located": 366,
        "coverage": 1.0
      },
      "5493007BWYDPQZLZ0Y27-2022-12-31-ESEF-AT-0": {
        "checked": 200,
        "confirmed": 200,
        "confirmed_rate": 1.0,
        "median_iou": 0.9474850409822342,
        "facts": 265,
        "located": 265,
        "coverage": 1.0
      }
    },
    "facts": 865,
    "located": 865,
    "coverage": 1.0,
    "checked": 600,
    "confirmed": 600,
    "confirmed_rate": 1.0,
    "median_iou": 0.9474850409822342
  },
  "narrative": {
    "sampled": 50,
    "auto_resolved": 19,
    "breakdown": {
      "exact": 18,
      "derived": 1,
      "unresolved": 31
    },
    "pool_all_untagged": 10738,
    "pool_prose": 1329,
    "review_file": "V:\\Antigravity\\Portfolio projects\\finrag-compliance-agent\\spikes\\esef_probe\\work\\narrative_review.csv",
    "note": "auto_resolved overcounts. Confirm rows in the CSV and use the confirmed count."
  }
}
```
