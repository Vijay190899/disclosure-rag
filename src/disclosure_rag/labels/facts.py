"""Extract tagged facts from an Inline XBRL document.

Reads ix:nonFraction attributes directly. ADR-0002 records why this uses lxml
rather than Arelle, and what would change that.

The number normalisation here is the most safety-critical code in the package.
An error in it does not announce itself: it rescales labels by a factor of a
thousand and every downstream measurement stays plausible while being wrong.
That failure mode is why the rules below are explicit and covered by tests.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Protocol

from lxml import etree
from pydantic import BaseModel, Field

IX = "http://www.xbrl.org/2013/inlineXBRL"
XBRLI = "http://www.xbrl.org/2003/instance"
XHTML = "http://www.w3.org/1999/xhtml"

# Each tagged fact is wrapped in an anchor pointing at this host before
# rendering. Chromium preserves anchors as PDF link annotations carrying the
# page and rectangle, which is how locate.py finds facts on the printed page.
# The URL is never resolved. See ADR-0002.
PROBE_URI = "https://label.invalid"

# Neutralise anchor styling so wrapping cannot shift the layout being measured.
ANCHOR_STYLE = (
    f'a[href^="{PROBE_URI}"] {{ color: inherit !important; '
    "text-decoration: none !important; background: none !important; }"
)


class Fact(BaseModel):
    """One tagged numeric fact, before it has been located on a page."""

    model_config = {"frozen": True}

    fact_id: str
    concept: str
    displayed: str = Field(description="The text a reader sees, before normalisation")
    value: Decimal = Field(description="Normalised value, with scale and sign applied")
    scale: int = 0
    sign: int = 1
    unit: str = ""
    context: str = ""
    period: str = ""


class FactSource(Protocol):
    """Reads tagged facts out of a filing.

    A protocol so the lxml reader can be swapped for Arelle without touching
    anything downstream. ADR-0002.
    """

    def extract(self, report: Path, stamped_out: Path | None = None) -> list[Fact]:
        """Return the tagged facts, optionally writing an anchor-stamped copy."""
        ...


def _decimal_separator(cleaned: str, fmt: str) -> str | None:
    """Which of . and , is the decimal point, or None if there is none.

    The Inline XBRL ``format`` attribute settles this outright when present,
    because it declares the transformation used. Guessing is only needed when
    the attribute is missing.

    The fallback matters because a lone separator group is genuinely ambiguous:
    "1.204" is 1204 under the Austrian and German convention and 1.204 under the
    English one. Exactly three digits after a lone separator means grouping,
    which is right for financial statements and also gets "0,5" right, since
    that has one digit after the comma.
    """
    normalised = (fmt or "").lower().replace("_", "-")
    if "comma-decimal" in normalised or "commadecimal" in normalised:
        return ","
    if "dot-decimal" in normalised or "dotdecimal" in normalised:
        return "."

    last_comma, last_dot = cleaned.rfind(","), cleaned.rfind(".")
    if last_comma >= 0 and last_dot >= 0:
        return "," if last_comma > last_dot else "."

    separator = "," if last_comma >= 0 else ("." if last_dot >= 0 else None)
    if separator is None:
        return None
    if cleaned.count(separator) > 1:
        return None  # repeated, so it is grouping
    return None if len(cleaned.split(separator)[-1]) == 3 else separator


def normalise_number(text: str, fmt: str = "") -> Decimal | None:
    """Turn the text a reader sees into the number it represents.

    Returns None when the text holds no usable number, which the caller treats
    as "not a numeric fact" rather than as an error.
    """
    cleaned = re.sub(r"[^\d,.\-()]", "", text or "").strip()
    if not cleaned:
        return None

    negative = cleaned.startswith("(") and cleaned.endswith(")")
    cleaned = cleaned.strip("()")
    if cleaned.startswith("-"):
        negative = True
        cleaned = cleaned[1:]

    separator = _decimal_separator(cleaned, fmt)
    if separator == ",":
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif separator == ".":
        cleaned = cleaned.replace(",", "")
    else:
        cleaned = cleaned.replace(",", "").replace(".", "")

    if not cleaned or cleaned == ".":
        return None
    try:
        value = Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None
    return -value if negative else value


class LxmlFactSource:
    """Reads ``ix:nonFraction`` elements directly. See ADR-0002."""

    def _units(self, tree: etree._ElementTree) -> dict[str, str]:
        """Map unit id to its measure, so a fact reports EUR rather than "u-1".

        ``unitRef`` is a document-local identifier pointing at a unit
        declaration. Surfacing it raw is wrong: a reader has no idea what "u-1"
        means, and neither does a downstream consumer.
        """
        units: dict[str, str] = {}
        for unit in tree.iter(f"{{{XBRLI}}}unit"):
            unit_id = unit.get("id")
            if not unit_id:
                continue
            measures = [
                (measure.text or "").strip()
                for measure in unit.iter(f"{{{XBRLI}}}measure")
                if (measure.text or "").strip()
            ]
            if not measures:
                continue
            # iso4217:EUR becomes EUR; xbrli:pure and xbrli:shares keep their name.
            units[unit_id] = "/".join(measure.rsplit(":", 1)[-1] for measure in measures)
        return units

    def _periods(self, tree: etree._ElementTree) -> dict[str, str]:
        """Map context id to a period.

        ``contextRef`` separates the current year from the prior-year
        comparative. Dropping it is the single most likely way to corrupt the
        whole label set, so it is resolved rather than ignored.
        """
        periods: dict[str, str] = {}
        for context in tree.iter(f"{{{XBRLI}}}context"):
            context_id = context.get("id")
            if not context_id:
                continue
            instant = context.find(f".//{{{XBRLI}}}instant")
            if instant is not None and instant.text:
                periods[context_id] = f"instant:{instant.text}"
                continue
            start = context.find(f".//{{{XBRLI}}}startDate")
            end = context.find(f".//{{{XBRLI}}}endDate")
            if start is not None and end is not None and start.text and end.text:
                periods[context_id] = f"{start.text}/{end.text}"
        return periods

    def _wrap(self, element: etree._Element, fact_id: str) -> None:
        """Wrap a fact in an anchor so it survives into the PDF as a link.

        The tail text moves to the anchor, otherwise the text following the
        number is duplicated or lost.
        """
        parent = element.getparent()
        if parent is None:
            return
        position = list(parent).index(element)
        anchor = etree.Element(f"{{{XHTML}}}a")
        anchor.set("href", f"{PROBE_URI}/{fact_id}")
        anchor.tail = element.tail
        element.tail = None
        parent.remove(element)
        anchor.append(element)
        parent.insert(position, anchor)

    def _inject_style(self, tree: etree._ElementTree) -> None:
        head = next(tree.iter(f"{{{XHTML}}}head"), None)
        if head is None:
            return
        style = etree.SubElement(head, f"{{{XHTML}}}style")
        style.set("type", "text/css")
        style.text = ANCHOR_STYLE

    def extract(self, report: Path, stamped_out: Path | None = None) -> list[Fact]:
        parser = etree.XMLParser(recover=True, huge_tree=True)
        tree = etree.parse(str(report), parser)
        periods = self._periods(tree)
        units = self._units(tree)

        facts: list[Fact] = []
        # Materialise first: wrapping mutates the tree while iterating over it.
        elements = list(tree.iter(f"{{{IX}}}nonFraction"))
        for index, element in enumerate(elements):
            displayed = "".join(element.itertext()).strip()
            base = normalise_number(displayed, element.get("format") or "")
            if base is None:
                continue

            scale = int(element.get("scale") or 0)
            sign = -1 if (element.get("sign") or "") == "-" else 1
            fact_id = f"f{index:06d}"
            context_ref = element.get("contextRef") or ""

            facts.append(
                Fact(
                    fact_id=fact_id,
                    concept=element.get("name") or "",
                    displayed=displayed,
                    value=base * (Decimal(10) ** scale) * sign,
                    scale=scale,
                    sign=sign,
                    unit=units.get(element.get("unitRef") or "", ""),
                    context=context_ref,
                    period=periods.get(context_ref, ""),
                )
            )
            if stamped_out is not None:
                self._wrap(element, fact_id)

        if stamped_out is not None:
            self._inject_style(tree)
            stamped_out.parent.mkdir(parents=True, exist_ok=True)
            tree.write(str(stamped_out), encoding="utf-8", method="xml")
        return facts
