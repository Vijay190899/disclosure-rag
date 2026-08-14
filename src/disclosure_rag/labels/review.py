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
from pathlib import Path

from disclosure_rag.labels.ledger import FactLedger, ProsePair

HELP = """
  y  yes, this is prose restating the figure
  n  no, it is a table row or a coincidence
  s  skip, decide later
  q  save and quit
"""


def pending(ledger: FactLedger) -> list[ProsePair]:
    """Unconfirmed candidates, likeliest first.

    ``names_concept`` is a weak signal on its own but a good sort key: pairs
    whose sentence also names the concept are far likelier to be genuine, so
    reviewing those first finds the usable ones early and the rest can be
    abandoned once enough are collected.
    """
    return sorted(
        (pair for pair in ledger.prose_pairs if not pair.confirmed),
        key=lambda pair: not pair.names_concept,
    )


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


def review_ledger(path: Path, limit: int | None = None) -> tuple[int, int]:
    """Walk one ledger's candidates. Returns (confirmed, reviewed)."""
    ledger = FactLedger.read(path)
    queue = pending(ledger)
    if limit is not None:
        queue = queue[:limit]
    if not queue:
        return 0, 0

    decisions: dict[str, bool] = {}
    confirmed = 0
    for position, pair in enumerate(queue, start=1):
        label = ledger.concept_labels.get(pair.concept, "")
        print(render(pair, position, len(queue), label))
        while True:
            choice = input("  [y/n/s/q] ").strip().lower()
            if choice in {"y", "n", "s", "q"}:
                break
            print(HELP)
        if choice == "q":
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
    return confirmed, len(decisions)


def main() -> int:
    parser = argparse.ArgumentParser(prog="disclosure_rag.labels.review", description=__doc__)
    parser.add_argument("--ledgers", type=Path, required=True)
    parser.add_argument(
        "--per-document",
        type=int,
        default=15,
        help="how many candidates to offer per filing before moving on",
    )
    args = parser.parse_args()

    paths = sorted(args.ledgers.glob("*/ledger.json"))
    if not paths:
        print(f"no ledgers under {args.ledgers}")
        return 1

    print(HELP)
    total_confirmed = total_reviewed = 0
    for path in paths:
        confirmed, reviewed = review_ledger(path, args.per_document)
        total_confirmed += confirmed
        total_reviewed += reviewed

    print(
        f"\nconfirmed {total_confirmed} of {total_reviewed} reviewed. "
        "Rerun the evaluation to pick up the narrative stratum."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
