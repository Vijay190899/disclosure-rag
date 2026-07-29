"""M2b probe: can table structure be recovered, and would it resolve the ambiguity?

Two measurements have now converged on the same conclusion: block-linearised
text loses the information needed to pick the right cell. Chunking fragmented
table rows (ADR-0010), and citation could not choose between a row's periods
(ADR-0011). Both point at table-aware parsing.

Before spending a week on it, this measures whether the structure is actually
recoverable from these documents, and whether recovering it would resolve the
specific ambiguity that is holding citation accuracy at 5.8%.

It tries PyMuPDF's built-in table finder first, because it is already a
dependency. If that suffices, Docling is not needed at all.

Thresholds are fixed here, before the probe was run, for the same reason the M0
thresholds were: so a disappointing result cannot be reinterpreted as a pass.
"""

from pathlib import Path

WORK = Path(__file__).parent / "work"
REPORT = Path(__file__).parent / "REPORT.md"

# A1. Are the tagged figures actually inside detected table cells? If the table
# finder cannot see the primary statements, nothing downstream matters.
MIN_FACTS_IN_CELLS = 0.60

# A2. Does the cell's column header carry the period? This is the exact
# information the citation selector lacks. Measured only over facts whose
# concept is reported for more than one period, since those are the ambiguous
# ones.
MIN_PERIOD_RESOLVABLE = 0.50

# A3. Can a detected cell serve as a citation region?
#
# The first version of this asked for IoU >= 0.5 between the cell and the tagged
# figure, and that threshold was mis-specified rather than merely strict. A cell
# contains a figure plus its padding, so cell-against-figure IoU is bounded near
# 0.05 by the area ratio no matter how good the detection is. That is the exact
# error ADR-0009 documented for blocks and this repeated it one level down.
#
# The right questions are whether the cell contains the figure, and how tightly,
# because tightness is what decides whether a cell is a useful thing to outline
# for a reader.
MIN_CELL_CONTAINMENT = 0.90
MIN_CELL_TIGHTNESS = 0.02

SAMPLE_FACTS = 200
