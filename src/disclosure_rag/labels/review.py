"""Confirm prose pairs, quickly.

    uv run python -m disclosure_rag.labels.review --ledgers data/ledgers

Mechanical extraction produces candidates and cannot promote them: a statement
row and a narrative sentence restating it contain the same label and the same
figure, so no available signal separates them. A person can tell in about two
seconds, which makes the bottleneck the interface rather than the judgement.

So this shows one candidate at a time, highest-likelihood first, and takes a
single keystroke. The question being answered each time is narrow:

    Is this sentence a person writing about the figure, or is it a table row?

Answers are written back into the ledgers, so the work survives a rebuild of
anything except the filings themselves.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import NamedTuple

from disclosure_rag.answer.router import pool_labels
from disclosure_rag.labels.ledger import FactLedger, ProsePair

HELP = """
  y  yes, this is prose restating the figure
  n  no, it is a table row or a coincidence
  s  skip, decide later
  q  save and stop
"""


WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
NUMBER = re.compile(r"-?\d[\d.,]*")

# Verbs and connectives a person writing about a figure uses and a table row
# does not. Deliberately short: the signal is that any of them appear at all.
NARRATIVE = frozenset(
    [
        "die",
        "der",
        "das",
        "und",
        "von",
        "mit",
        "auf",
        "sich",
        "sowie",
        "durch",
        "für",
        "ist",
        "sind",
        "war",
        "waren",
        "wird",
        "werden",
        "wurde",
        "wurden",
        "hat",
        "haben",
        "betrug",
        "betragen",
        "beträgt",
        "stieg",
        "stiegen",
        "sank",
        "sanken",
        "lag",
        "lagen",
        "belief",
        "beliefen",
        "erhöhte",
        "erhöhten",
        "reduzierte",
        "reduzierten",
        "gegenüber",
        "infolge",
        "aufgrund",
        "somit",
        "damit",
        "konnte",
        "konnten",
        "enthalten",
        "ergibt",
        "resultiert",
        "entspricht",
    ]
)


def _stems(text: str) -> set[str]:
    """Case-folded prefixes, so "langfristigen" and "Langfristige" agree.

    German inflection is why the stored ``names_concept`` flag is nearly useless
    as a sort key: it does exact term matching, so it fired on 8 of 495
    candidates while the genuine pairs it missed were mostly inflected forms of
    the label.
    """
    return {word.lower()[:6] for word in WORD.findall(text) if len(word) > 3}


def score(pair: ProsePair, label: str) -> float:
    """How likely a candidate is to be a person writing about the figure.

    Two factors, multiplied because both are necessary. Label overlap says the
    sentence is about the right concept. Prose likeness says it is a sentence
    at all, and it is the one that matters: ranking on overlap alone puts
    statement rows at the top, because a row's text *is* the concept label.
    """
    label_stems = _stems(label)
    if not label_stems:
        return 0.0
    overlap = len(label_stems & _stems(pair.sentence)) / len(label_stems)

    words = WORD.findall(pair.sentence)
    if len(words) < 6:
        return 0.0
    numbers = len(NUMBER.findall(pair.sentence))
    sparse = max(0.0, 1 - 3 * numbers / (numbers + len(words)))
    narrative = min(1.0, len({word.lower() for word in words} & NARRATIVE) / 3)
    return overlap * sparse * narrative


def best_score(pair: ProsePair, ledger: FactLedger, pooled: dict[str, set[str]] | None) -> float:
    """The best score over every wording available for the pair's concept.

    Pooling matters more here than anywhere else in the system. Ranking on a
    filing's own labels alone puts 14 candidates above the floor across the
    corpus; allowing another issuer's wording for the same concept puts 28
    there, and the ones it adds are ordinary MD&A sentences, not marginal
    cases.
    """
    wordings = set(pooled.get(pair.concept, set())) if pooled else set()
    own = ledger.concept_labels.get(pair.concept, "")
    if own:
        wordings.add(own)
    return max((score(pair, wording) for wording in wordings), default=0.0)


def pending(
    ledger: FactLedger,
    floor: float = 0.0,
    pooled: dict[str, set[str]] | None = None,
) -> list[ProsePair]:
    """Unconfirmed candidates, likeliest first.

    ``floor`` cuts the tail: below roughly 0.15 the queue is statement rows that
    happen to contain a figure, and reviewing those is how a reviewer learns to
    press "n" without reading. Pass 0 to see everything.
    """
    scored = [
        (best_score(pair, ledger, pooled), index, pair)
        for index, pair in enumerate(ledger.prose_pairs)
        if not pair.confirmed
    ]
    return [pair for value, _, pair in sorted(scored, key=lambda row: -row[0]) if value >= floor]


def render(pair: ProsePair, index: int, total: int, label: str) -> str:
    return "\n".join(
        [
            "",
            "=" * 78,
            f"[{index}/{total}]  {pair.document_id}  page {pair.page}",
            "",
            f"  figure in the text : {pair.mention}",
            f"  tagged concept     : {label or pair.concept}",
            f"  tagged value       : {pair.value}",
            "",
            "  sentence:",
            f"    {pair.sentence}",
            "",
        ]
    )


class Session(NamedTuple):
    confirmed: int
    reviewed: int
    stop: bool


def review_ledger(
    path: Path,
    limit: int | None = None,
    floor: float = 0.0,
    pooled: dict[str, set[str]] | None = None,
) -> Session:
    """Walk one ledger's candidates.

    Whatever was decided before quitting is written. A review tool that discards
    the work when someone stops early teaches them not to stop early, which is
    the opposite of what a queue this long needs.
    """
    ledger = FactLedger.read(path)
    queue = pending(ledger, floor, pooled)
    if limit is not None:
        queue = queue[:limit]
    if not queue:
        return Session(0, 0, stop=False)

    decisions: dict[str, bool] = {}
    confirmed = 0
    stop = False
    for position, pair in enumerate(queue, start=1):
        label = ledger.concept_labels.get(pair.concept, "")
        print(render(pair, position, len(queue), label))
        choice = ""
        while choice not in {"y", "n", "s", "q"}:
            try:
                choice = input("  [y/n/s/q] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                # Ctrl-C, Ctrl-D or a piped run that ran out of input. Save and
                # leave rather than exiting with a traceback over a decision
                # someone deliberately made.
                print()
                choice = "q"
            if choice not in {"y", "n", "s", "q"}:
                print(HELP)
        if choice == "q":
            stop = True
            break
        if choice == "s":
            continue
        decisions[pair.fact_id + pair.mention] = choice == "y"
        confirmed += choice == "y"

    if decisions:
        ledger.prose_pairs = [
            pair.model_copy(update={"confirmed": True})
            if decisions.get(pair.fact_id + pair.mention)
            else pair
            for pair in ledger.prose_pairs
        ]
        ledger.write(path)
    return Session(confirmed, len(decisions), stop)


def main() -> int:
    parser = argparse.ArgumentParser(prog="disclosure_rag.labels.review", description=__doc__)
    parser.add_argument("--ledgers", type=Path, required=True)
    parser.add_argument(
        "--per-document",
        type=int,
        default=10,
        help="how many candidates to offer per filing before moving on",
    )
    parser.add_argument(
        "--floor",
        type=float,
        default=0.15,
        help="skip candidates scoring below this. 0 offers everything.",
    )
    args = parser.parse_args()

    paths = sorted(args.ledgers.glob("*/ledger.json"))
    if not paths:
        print(f"no ledgers under {args.ledgers}")
        return 1

    # Every wording any filing declares, so a concept this filing left unlabelled
    # can still be recognised. See best_score.
    pooled = pool_labels({path.parent.name: FactLedger.read(path) for path in paths})

    print(HELP)
    total_confirmed = total_reviewed = 0
    for path in paths:
        session = review_ledger(path, args.per_document, args.floor, pooled)
        total_confirmed += session.confirmed
        total_reviewed += session.reviewed
        if session.stop:
            break

    print(
        f"\nconfirmed {total_confirmed} of {total_reviewed} reviewed, saved to the ledgers. "
        "Run `make eval` to pick up the narrative stratum."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
