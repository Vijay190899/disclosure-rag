"""M0 probe: does the Inline XBRL oracle idea actually hold up?

See README.md in this directory for the assumptions under test and the abort
criteria, which were written before the probe was run.
"""

from pathlib import Path

WORK = Path(__file__).parent / "work"
FILINGS = WORK / "filings"
RENDERS = WORK / "renders"
LEDGER = WORK / "ledger.json"
GEOMETRY_REPORT = WORK / "geometry_check.json"
NARRATIVE_REVIEW = WORK / "narrative_review.csv"
NARRATIVE_REPORT = WORK / "narrative_check.json"

# Abort thresholds. Fixed in advance so the result cannot be reinterpreted later.
MIN_NARRATIVE_RESOLVED = 20  # out of NARRATIVE_SAMPLE_SIZE
NARRATIVE_SAMPLE_SIZE = 50
MIN_GEOMETRY_CONFIRMED_RATE = 0.90
MIN_GEOMETRY_MEDIAN_IOU = 0.5

TARGET_FILINGS = 3


def ensure_dirs() -> None:
    for directory in (WORK, FILINGS, RENDERS):
        directory.mkdir(parents=True, exist_ok=True)
