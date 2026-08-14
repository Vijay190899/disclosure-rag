"""Rendering a ledger period the way a reader would write it.

This lives on its own because both the evaluation harness and the serving plane
phrase periods, and they have to phrase them identically. A question that reads
well in a benchmark and differently in the product is two systems being measured
as one.
"""

from __future__ import annotations


def _german_date(iso: str) -> str:
    """2022-12-31 becomes 31.12.2022, which is how the corpus writes dates."""
    parts = iso.split("-")
    if len(parts) != 3:
        return iso
    year, month, day = parts
    return f"{day}.{month}.{year}"


def describe_period(period: str) -> str:
    """Render a ledger period the way the documents write it.

    This was previously emitting ISO dates, which was quietly poisoning every
    query. The lexical tokenizer splits on hyphens, so "2022-01-01 bis
    2022-12-31" became six separate numeric tokens, `2022 01 01 2022 12 31`,
    against roughly four content tokens. Those numerals match figures on nearly
    every table page in a filing, so the period phrase was actively misleading
    retrieval rather than merely failing to help.

    German date format fixes both halves of that. It is what the filings
    actually print, and because the tokenizer treats a full stop as an internal
    separator, "31.12.2022" survives as a single token instead of three.
    """
    if period.startswith("instant:"):
        return f"zum {_german_date(period.removeprefix('instant:'))}"
    if "/" in period:
        start, end = period.split("/", 1)
        # A full financial year is how a reader would refer to it.
        if start.endswith("-01-01") and end.endswith("-12-31") and start[:4] == end[:4]:
            return f"im Geschäftsjahr {start[:4]}"
        return f"für den Zeitraum {_german_date(start)} bis {_german_date(end)}"
    return ""


def phrase_question(label: str, period: str) -> str:
    """The one phrasing used for a figure question, everywhere."""
    return f"Wie hoch war {label} {describe_period(period)}?".replace("  ", " ")
