"""Build fact ledgers from a directory of filings.

    uv run python -m disclosure_rag.labels.build --filings data/filings --out data/ledgers

Expects each filing as ``<filings>/<document_id>/report.xhtml``. Two renderings
happen per document, and the difference matters: the *stamped* copy carries the
anchors and is used only to read locations, while the *plain* copy is what the
serving plane will ingest. Keeping them separate is what stops a tag leaking
into the system under test.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from disclosure_rag.labels.facts import LxmlFactSource
from disclosure_rag.labels.ledger import FactLedger, build, write_index, write_review_csv
from disclosure_rag.labels.locate import confirm_by_text, locate_facts, render_to_pdf
from disclosure_rag.labels.taxonomy import load_labels


def _page_blocks(pdf_path: Path) -> list[list[str]]:
    """Layout blocks per page, not whole-page text.

    A page dump runs headers, tables and paragraphs together into one string,
    and anything reading sentences out of that gets blobs that look like prose
    without being prose. Blocks preserve the paragraph boundaries.
    """
    import fitz

    document = fitz.open(pdf_path)
    try:
        return [
            [block[4] for block in document[number].get_text("blocks") if block[4].strip()]
            for number in range(document.page_count)
        ]
    finally:
        document.close()


def build_one(report: Path, out_dir: Path, source: LxmlFactSource | None = None) -> FactLedger:
    document_id = report.parent.name
    source = source or LxmlFactSource()
    work = out_dir / document_id
    work.mkdir(parents=True, exist_ok=True)

    stamped = work / "report.stamped.xhtml"
    facts = source.extract(report, stamped_out=stamped)

    # Label linkbases sit alongside the report inside the ESEF package. Without
    # them the question generator falls back to English concept names, which
    # the documents do not contain. See ADR-0009.
    concept_labels = load_labels(report.parent)
    used = {fact.concept for fact in facts}
    matched = len(used & concept_labels.keys())
    print(
        f"[labels] {document_id}: {len(facts)} tagged numeric facts, "
        f"{matched}/{len(used)} concepts have a declared label"
    )

    stamped_pdf = render_to_pdf(stamped, work / "stamped.pdf")
    located = locate_facts(stamped_pdf)
    confirmation = confirm_by_text(
        stamped_pdf, located, {fact.fact_id: fact.displayed for fact in facts}
    )
    print(
        f"[labels] {document_id}: located {len(located)}/{len(facts)}, "
        f"confirmed {confirmation.confirmed_rate:.1%}, "
        f"median IoU {confirmation.median_iou:.3f}"
    )

    # The plain rendering is the artefact the serving plane will consume. It has
    # no anchors and no tags, and it is what prose text is read from.
    plain_pdf = render_to_pdf(report, work / "document.pdf")

    ledger = build(
        document_id, facts, located, _page_blocks(plain_pdf), confirmation, concept_labels
    )
    ledger.write(work / "ledger.json")
    print(f"[labels] {document_id}: {len(ledger.prose_pairs)} prose pairs")
    return ledger


def main() -> int:
    parser = argparse.ArgumentParser(prog="disclosure_rag.labels.build", description=__doc__)
    parser.add_argument("--filings", type=Path, required=True, help="directory of filings")
    parser.add_argument("--out", type=Path, required=True, help="where ledgers are written")
    args = parser.parse_args()

    reports = sorted(args.filings.glob("*/report.xhtml"))
    if not reports:
        print(f"no filings found under {args.filings}")
        return 1

    ledgers = [build_one(report, args.out) for report in reports]
    write_index(ledgers, args.out / "index.json")
    review = args.out / "prose_pairs_review.csv"
    candidates = write_review_csv(ledgers, review)

    print(
        f"\n[labels] {len(ledgers)} documents, "
        f"{sum(len(item.facts) for item in ledgers)} located facts, "
        f"{candidates} prose-pair candidates"
    )
    if candidates:
        print(
            f"[labels] candidates need review before use as labels: {review}\n"
            "[labels] table rows that read as prose, and coincidental value "
            "matches, both survive the filters."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
