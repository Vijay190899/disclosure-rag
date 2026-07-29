"""Stage 2: pull the tagged facts out of the Inline XBRL.

Reads ix:nonFraction elements directly with lxml. Arelle is the right tool for
M1, because it resolves contexts, continuations and dimensions properly. For a
probe, attribute reading answers the question with far fewer moving parts.

The part that matters and is easy to get wrong is normalisation. The text a
reader sees is not the value: "1,204" carrying scale="6" is 1204000000, and
sign="-" makes it negative. Getting this wrong would silently corrupt every
label, so it is the one piece of the probe with real care in it.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

from lxml import etree

from . import FILINGS, LEDGER, ensure_dirs

IX = "http://www.xbrl.org/2013/inlineXBRL"
XBRLI = "http://www.xbrl.org/2003/instance"

PROBE_ID_ATTR = "data-probe-id"


def _decimal_separator(cleaned: str, fmt: str) -> str | None:
    """Work out which of . and , is the decimal point, or None if there is none.

    The format attribute settles it outright when present. Inline XBRL declares
    the convention through a transformation such as ixt:num-comma-decimal, so
    guessing is only necessary when the attribute is missing.

    The fallback matters because a single separator group is genuinely
    ambiguous: "1.204" is 1204 under the German convention and 1.204 under the
    English one. Three digits after the separator means grouping, which is the
    right call for financial statements and gets "0,5" right as well because it
    has only one digit after the comma.
    """
    normalised_fmt = (fmt or "").lower().replace("_", "-")
    if "comma-decimal" in normalised_fmt or "commadecimal" in normalised_fmt:
        return ","
    if "dot-decimal" in normalised_fmt or "dotdecimal" in normalised_fmt:
        return "."

    last_comma, last_dot = cleaned.rfind(","), cleaned.rfind(".")
    if last_comma >= 0 and last_dot >= 0:
        # Both present: the later one is the decimal point.
        return "," if last_comma > last_dot else "."

    separator = "," if last_comma >= 0 else ("." if last_dot >= 0 else None)
    if separator is None:
        return None
    if cleaned.count(separator) > 1:
        return None  # repeated, so it is grouping
    return None if len(cleaned.split(separator)[-1]) == 3 else separator


def normalise_number(text: str, fmt: str = "") -> Decimal | None:
    """Turn the text a reader sees into the number it represents.

    This is the piece of the probe with real care in it. An error here would not
    announce itself: it would silently rescale every label by a factor of a
    thousand, and every downstream measurement would look plausible and be
    wrong.
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


def _periods(tree) -> dict[str, str]:
    """Map context id to a human-readable period.

    contextRef is what separates the current year from the prior-year
    comparative. Dropping it is the single most likely way to corrupt the
    entire label set, which is why it is resolved here rather than ignored.
    """
    periods: dict[str, str] = {}
    for context in tree.iter(f"{{{XBRLI}}}context"):
        context_id = context.get("id")
        if not context_id:
            continue
        instant = context.find(f".//{{{XBRLI}}}instant")
        if instant is not None:
            periods[context_id] = f"instant:{instant.text}"
            continue
        start = context.find(f".//{{{XBRLI}}}startDate")
        end = context.find(f".//{{{XBRLI}}}endDate")
        if start is not None and end is not None:
            periods[context_id] = f"{start.text}/{end.text}"
    return periods


def extract(report: Path) -> list[dict]:
    parser = etree.XMLParser(recover=True, huge_tree=True)
    tree = etree.parse(str(report), parser)
    periods = _periods(tree)

    facts: list[dict] = []
    for index, element in enumerate(tree.iter(f"{{{IX}}}nonFraction")):
        displayed = "".join(element.itertext()).strip()
        base = normalise_number(displayed, element.get("format") or "")
        if base is None:
            continue

        scale = int(element.get("scale") or 0)
        sign = -1 if (element.get("sign") or "") == "-" else 1
        value = base * (Decimal(10) ** scale) * sign

        probe_id = f"f{index:06d}"
        # Stamp an id so the geometry stage can find this exact element again.
        element.set(PROBE_ID_ATTR, probe_id)

        context_ref = element.get("contextRef") or ""
        facts.append(
            {
                "probe_id": probe_id,
                "concept": element.get("name") or "",
                "displayed": displayed,
                "value": str(value),
                "scale": scale,
                "sign": sign,
                "unit": element.get("unitRef") or "",
                "context": context_ref,
                "period": periods.get(context_ref, ""),
            }
        )

    # Write the stamped copy: the geometry stage renders this, not the original,
    # so browser boxes can be tied back to specific facts.
    stamped = report.with_name("report.stamped.xhtml")
    tree.write(str(stamped), encoding="utf-8", method="xml")
    return facts


def run() -> dict:
    ensure_dirs()
    ledger: dict[str, list[dict]] = {}
    for report in sorted(FILINGS.glob("*/report.xhtml")):
        facts = extract(report)
        ledger[report.parent.name] = facts
        print(f"[facts] {report.parent.name}: {len(facts)} tagged numeric facts")

    if not ledger:
        print("[facts] no filings found, run the fetch stage first")

    LEDGER.write_text(json.dumps(ledger, indent=2), encoding="utf-8")
    total = sum(len(v) for v in ledger.values())
    print(f"[facts] wrote {total} facts to {LEDGER}")
    return ledger
