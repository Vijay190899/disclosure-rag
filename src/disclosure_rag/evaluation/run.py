"""Run a retriever over the question set and print the results table.

    uv run python -m disclosure_rag.evaluation.run --ledgers data/ledgers

The ledger directory supplies both halves: the rendered document the serving
plane ingests, and the gold spans it is scored against. The retriever never sees
the second.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from disclosure_rag.evaluation.metrics import Result, StratumScore, score_run
from disclosure_rag.evaluation.questions import Question, questions_from_ledger
from disclosure_rag.ingest.blocks import extract_blocks
from disclosure_rag.ingest.chunker import Chunk, chunk_blocks
from disclosure_rag.labels.ledger import FactLedger
from disclosure_rag.retrieval.base import Retriever
from disclosure_rag.retrieval.lexical import BM25Retriever


def load(ledger_dir: Path) -> tuple[list[Chunk], list[Question]]:
    """Ingest every document under a ledger directory and build the questions."""
    chunks: list[Chunk] = []
    questions: list[Question] = []

    for ledger_path in sorted(ledger_dir.glob("*/ledger.json")):
        ledger = FactLedger.read(ledger_path)
        document_pdf = ledger_path.parent / "document.pdf"
        if not document_pdf.exists():
            print(f"[eval] skipping {ledger.document_id}: no rendered document")
            continue

        blocks = extract_blocks(document_pdf)
        document_chunks = chunk_blocks(ledger.document_id, blocks)
        chunks.extend(document_chunks)

        document_questions = questions_from_ledger(ledger)
        questions.extend(document_questions)
        print(
            f"[eval] {ledger.document_id}: {len(blocks)} blocks, "
            f"{len(document_chunks)} chunks, {len(document_questions)} questions"
        )

    return chunks, questions


def evaluate(
    retriever: Retriever,
    chunks: list[Chunk],
    questions: list[Question],
    top_k: int = 10,
) -> list[StratumScore]:
    """Index, run every question, and score."""
    retriever.index(chunks)
    results: dict[str, Result] = {}
    for question in questions:
        hits = retriever.search(question.text, top_k=top_k)
        results[question.question_id] = Result(
            question_id=question.question_id,
            stratum=question.stratum,
            retrieved_spans=[hit.chunk.spans for hit in hits],
        )
    return score_run(questions, results)


def render_table(name: str, scores: list[StratumScore]) -> str:
    lines = [
        f"\nRetriever: {name}",
        "",
        "| Stratum | n | recall@1 | recall@5 | recall@10 | coverage@1 "
        "| shown first when found | tightness |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for score in scores:
        lines.append(
            f"| {score.stratum.value} | {score.questions} | "
            f"{score.recall_at_1:.3f} | {score.recall_at_5:.3f} | {score.recall_at_10:.3f} | "
            f"{score.citation_coverage_at_1:.3f} | {score.shown_first_when_found:.3f} | "
            f"{score.mean_tightness:.3f} |"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(prog="disclosure_rag.evaluation.run", description=__doc__)
    parser.add_argument("--ledgers", type=Path, required=True)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--out", type=Path, default=None, help="write scores as JSON")
    args = parser.parse_args()

    chunks, questions = load(args.ledgers)
    if not chunks or not questions:
        print("[eval] nothing to evaluate")
        return 1

    print(f"\n[eval] {len(chunks)} chunks, {len(questions)} questions")

    retriever = BM25Retriever()
    scores = evaluate(retriever, chunks, questions, top_k=args.top_k)
    print(render_table(retriever.name, scores))

    print(
        "\n[eval] strata are reported separately and must not be pooled. "
        "exact_figure is the easy control, not the headline. See ADR-0008."
    )

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(
                {
                    "retriever": retriever.name,
                    "chunks": len(chunks),
                    "questions": len(questions),
                    "scores": [score.model_dump(mode="json") for score in scores],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"[eval] wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
