"""Run the ablation ladder and print the results.

    uv run python -m disclosure_rag.evaluation.run --ledgers data/ledgers

Each rung adds one component to the previous one, and every rung reports what it
bought as a paired confidence interval on the same questions. A component that
does not earn a row comes out of the stack, including the ones I expect to work.

The ledger directory supplies both halves: the rendered document the serving
plane ingests, and the gold spans it is scored against. No retriever sees the
second.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from disclosure_rag.citation import select_numeric_spans
from disclosure_rag.evaluation.metrics import (
    COVERAGE_THRESHOLD,
    Result,
    StratumScore,
    score_run,
)
from disclosure_rag.evaluation.questions import Question, Stratum, questions_from_ledger
from disclosure_rag.evaluation.stats import Delta, paired_bootstrap
from disclosure_rag.ingest.blocks import extract_blocks
from disclosure_rag.ingest.chunker import Chunk, chunk_blocks
from disclosure_rag.labels.ledger import FactLedger
from disclosure_rag.provenance import Span
from disclosure_rag.retrieval.base import Retriever
from disclosure_rag.retrieval.lexical import BM25Retriever


def load(
    ledger_dir: Path, chunk_tokens: int = 600, overlap_tokens: int = 80
) -> tuple[list[Chunk], list[Question], dict[str, Path]]:
    """Ingest every document under a ledger directory and build the questions."""
    ledgers = [FactLedger.read(path) for path in sorted(ledger_dir.glob("*/ledger.json"))]

    # Labels declared by any filing are available to all. See questions.py.
    pooled: dict[str, str] = {}
    for ledger in ledgers:
        pooled.update(ledger.concept_labels)

    chunks: list[Chunk] = []
    questions: list[Question] = []
    pdf_for: dict[str, Path] = {}
    for ledger, path in zip(ledgers, sorted(ledger_dir.glob("*/ledger.json")), strict=True):
        document_pdf = path.parent / "document.pdf"
        if not document_pdf.exists():
            print(f"[eval] skipping {ledger.document_id}: no rendered document")
            continue

        pdf_for[ledger.document_id] = document_pdf
        blocks = extract_blocks(document_pdf)
        document_chunks = chunk_blocks(
            ledger.document_id, blocks, target_tokens=chunk_tokens, overlap_tokens=overlap_tokens
        )
        chunks.extend(document_chunks)

        document_questions = questions_from_ledger(ledger, pooled_labels=pooled)
        questions.extend(document_questions)
        pooled_count = sum(1 for q in document_questions if q.label_source == "pooled")
        print(
            f"[eval] {ledger.document_id}: {len(blocks)} blocks, "
            f"{len(document_chunks)} chunks, {len(document_questions)} questions "
            f"({pooled_count} from pooled labels)"
        )

    return chunks, questions, pdf_for


def run_retriever(
    retriever: Retriever,
    chunks: list[Chunk],
    questions: list[Question],
    top_k: int = 10,
    pdf_for: dict[str, Path] | None = None,
) -> dict[str, Result]:
    retriever.index(chunks)
    results: dict[str, Result] = {}
    for question in questions:
        # Scoped to the filing being asked about: see Retriever.search.
        hits = retriever.search(question.text, top_k=top_k, document_id=question.document_id)
        # Narrow the top result to the figures it would outline for a reader.
        # Without this the citation metric collapses onto rank-1 recall. See
        # citation.py.
        cited: list[Span] = []
        if hits and pdf_for and question.document_id in pdf_for:
            cited = select_numeric_spans(
                pdf_for[question.document_id], hits[0].chunk, question.text
            )
        results[question.question_id] = Result(
            question_id=question.question_id,
            stratum=question.stratum,
            retrieved_spans=[hit.chunk.spans for hit in hits],
            cited_spans=cited,
        )
    return results


def per_question_hits(questions: list[Question], results: dict[str, Result], k: int) -> list[float]:
    """One score per question, in a fixed order, for the paired comparison."""
    scores: list[float] = []
    for question in questions:
        result = results.get(
            question.question_id,
            Result(question_id=question.question_id, stratum=question.stratum),
        )
        rank = result.hit_rank(question.gold_spans, COVERAGE_THRESHOLD)
        scores.append(1.0 if rank is not None and rank <= k else 0.0)
    return scores


def render_scores(name: str, scores: list[StratumScore]) -> str:
    lines = [
        f"\n{name}",
        "| Stratum | n | recall@1 | recall@5 | recall@10 | shown first when found "
        "| citation IoU@0.5 | mean citation IoU |",
        "|---|---|---|---|---|---|---|",
    ]
    for score in scores:
        lines.append(
            f"| {score.stratum.value} | {score.questions} | "
            f"{score.recall_at_1:.3f} | {score.recall_at_5:.3f} | {score.recall_at_10:.3f} | "
            f"{score.shown_first_when_found:.3f} | {score.citation_iou_at_50:.3f} | "
            f"{score.mean_citation_iou:.3f} |"
        )
    return "\n".join(lines)


def build_ladder(dense_model: str | None) -> list[Retriever]:
    """The rungs, each adding one component to the one before it."""
    ladder: list[Retriever] = [BM25Retriever()]
    if dense_model:
        from disclosure_rag.retrieval.dense import DenseRetriever
        from disclosure_rag.retrieval.hybrid import HybridRetriever

        dense = DenseRetriever(dense_model)
        ladder.append(dense)
        ladder.append(HybridRetriever([BM25Retriever(), DenseRetriever(dense_model)]))
    return ladder


def main() -> int:
    parser = argparse.ArgumentParser(prog="disclosure_rag.evaluation.run", description=__doc__)
    parser.add_argument("--ledgers", type=Path, required=True)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument(
        "--chunk-tokens",
        type=int,
        default=600,
        help="chunk size budget. Must fit the embedding model's window, see dense.py",
    )
    parser.add_argument("--overlap-tokens", type=int, default=80)
    parser.add_argument(
        "--dense-model",
        default=None,
        help="enable the dense and hybrid rungs with this fastembed model",
    )
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    chunks, questions, pdf_for = load(args.ledgers, args.chunk_tokens, args.overlap_tokens)
    if not chunks or not questions:
        print("[eval] nothing to evaluate")
        return 1
    print(f"\n[eval] {len(chunks)} chunks, {len(questions)} questions")

    ladder = build_ladder(args.dense_model)
    report: dict[str, object] = {
        "chunks": len(chunks),
        "chunk_tokens": args.chunk_tokens,
        "questions": len(questions),
        "runs": [],
    }
    runs: list[tuple[str, dict[str, Result], list[StratumScore]]] = []

    for retriever in ladder:
        print(f"\n[eval] running {retriever.name}")
        results = run_retriever(retriever, chunks, questions, args.top_k, pdf_for)
        scores = score_run(questions, results)
        runs.append((retriever.name, results, scores))
        print(render_scores(retriever.name, scores))

    # Deltas against the previous rung, on the exact-figure stratum.
    figure_questions = [q for q in questions if q.stratum == Stratum.EXACT_FIGURE]
    deltas: list[tuple[str, str, Delta]] = []
    if len(runs) > 1 and figure_questions:
        print("\n[eval] recall@5 deltas, paired bootstrap 95% interval")
        for (previous_name, previous, _), (name, current, _) in zip(runs, runs[1:], strict=False):
            delta = paired_bootstrap(
                per_question_hits(figure_questions, previous, 5),
                per_question_hits(figure_questions, current, 5),
            )
            deltas.append((previous_name, name, delta))
            print(f"  {previous_name} -> {name}: {delta.render()}")
            print(f"    n={delta.n}, questions where the two disagree={delta.discordant}")

    print(
        "\n[eval] strata are reported separately and never pooled. exact_figure is "
        "the easy control, not the headline. See ADR-0008."
    )

    if args.out:
        report["runs"] = [
            {"retriever": name, "scores": [s.model_dump(mode="json") for s in scores]}
            for name, _, scores in runs
        ]
        report["deltas"] = [
            {"from": a, "to": b, **delta.model_dump(mode="json")} for a, b, delta in deltas
        ]
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"[eval] wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
