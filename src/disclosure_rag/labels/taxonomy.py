"""Read concept labels out of an XBRL label linkbase.

Concept names are English and these filings are German, so a question built from
a concept name shares no vocabulary with the document it asks about. The label
the issuer declared is what a reader would call the thing, and it is what both
the router and the question generator use.

An ESEF report package ships a label linkbase, usually named ``*_lab-de.xml``,
which declares the issuer's German label for every concept the report uses,
including the standard IFRS ones. That is the canonical name for the concept
rather than the exact string rendered in one table row, which matters: a query
built from the row text would be most of the way to handing the retriever its
target, whereas the concept's declared label is what a person would actually
call the thing.

Structure of a linkbase, which is why the join below looks the way it does:

    <link:loc      xlink:href="...#ifrs-full_Revenue" xlink:label="loc_1"/>
    <link:label    xlink:label="lab_1" xml:lang="de">Umsatzerlöse</link:label>
    <link:labelArc xlink:from="loc_1" xlink:to="lab_1"/>

So the locator names a concept, the label holds the text, and the arc connects
them. Nothing is nested, so all three have to be read and joined by key.
"""

from __future__ import annotations

from pathlib import Path

from lxml import etree

LINK = "http://www.xbrl.org/2003/linkbase"
XLINK = "http://www.w3.org/1999/xlink"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"

STANDARD_LABEL = "http://www.xbrl.org/2003/role/label"

# Preference order when a concept carries several labels. The plain label is the
# concept's name; the others are presentation variants ("Total revenue",
# "Revenue, net") that read worse as a question subject.
ROLE_PRIORITY = (
    STANDARD_LABEL,
    "http://www.xbrl.org/2003/role/terseLabel",
    "http://www.xbrl.org/2003/role/totalLabel",
    "http://www.xbrl.org/2003/role/verboseLabel",
)


def concept_from_href(href: str) -> str:
    """Turn a locator href into the concept name used in the report.

    ``.../full_ifrs-cor_2022-03-24.xsd#ifrs-full_Revenue`` becomes
    ``ifrs-full:Revenue``. Element ids follow the prefix_LocalName convention,
    so the split is on the first underscore only: local names contain
    underscores, prefixes do not.
    """
    if "#" not in href:
        return ""
    fragment = href.rsplit("#", 1)[1]
    if "_" not in fragment:
        return ""
    prefix, local = fragment.split("_", 1)
    return f"{prefix}:{local}"


def parse_linkbase(path: Path, language: str = "de") -> dict[str, str]:
    """Concept name to label, for one linkbase file."""
    try:
        root = etree.parse(str(path), etree.XMLParser(recover=True, huge_tree=True)).getroot()
    except (OSError, etree.XMLSyntaxError):
        return {}

    # Locator key to concept name.
    concepts: dict[str, str] = {}
    for loc in root.iter(f"{{{LINK}}}loc"):
        key = loc.get(f"{{{XLINK}}}label")
        concept = concept_from_href(loc.get(f"{{{XLINK}}}href") or "")
        if key and concept:
            concepts[key] = concept

    # Label key to (role, text), keeping only the requested language.
    texts: dict[str, tuple[str, str]] = {}
    for label in root.iter(f"{{{LINK}}}label"):
        key = label.get(f"{{{XLINK}}}label")
        text = (label.text or "").strip()
        if not key or not text:
            continue
        if language and (label.get(XML_LANG) or "").lower() != language.lower():
            continue
        texts[key] = (label.get(f"{{{XLINK}}}role") or "", text)

    # Join across the arcs, keeping the best-ranked role per concept.
    best: dict[str, tuple[int, str]] = {}
    for arc in root.iter(f"{{{LINK}}}labelArc"):
        target = concepts.get(arc.get(f"{{{XLINK}}}from") or "")
        entry = texts.get(arc.get(f"{{{XLINK}}}to") or "")
        if not target or not entry:
            continue
        role, label_text = entry
        rank = ROLE_PRIORITY.index(role) if role in ROLE_PRIORITY else len(ROLE_PRIORITY)
        if target not in best or rank < best[target][0]:
            best[target] = (rank, label_text)

    return {concept: text for concept, (_, text) in best.items()}


def load_labels(directory: Path, language: str = "de") -> dict[str, str]:
    """Merge every label linkbase found beneath a directory.

    Earlier files win, so a report's own linkbase is not overwritten by one
    picked up from a bundled copy of the standard taxonomy.
    """
    merged: dict[str, str] = {}
    for path in sorted(directory.rglob("*lab*.xml")):
        for concept, text in parse_linkbase(path, language).items():
            merged.setdefault(concept, text)
    return merged
