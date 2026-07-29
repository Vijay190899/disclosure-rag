"""The label plane.

Reads Inline XBRL and produces gold labels: what each tagged number means and
where it sits on the printed page. Section 5 of the technical documentation.

Nothing in the serving plane may import from here. The separation is what makes
the benchmark honest, and it is enforced by a test rather than by good manners.
"""

from disclosure_rag.labels.facts import Fact, FactSource, LxmlFactSource, normalise_number
from disclosure_rag.labels.ledger import FactLedger, ProsePair
from disclosure_rag.labels.locate import locate_facts

__all__ = [
    "Fact",
    "FactLedger",
    "FactSource",
    "LxmlFactSource",
    "ProsePair",
    "locate_facts",
    "normalise_number",
]
