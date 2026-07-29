"""Load a built corpus into memory: ledgers, chunks, and a live index.

One place that knows how a ledger directory maps onto a running service, so the
API, the evaluation harness and the viewer all load the corpus identically and
cannot drift into measuring different things.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from disclosure_rag.ingest.blocks import extract_blocks, page_count
from disclosure_rag.ingest.chunker import Chunk, chunk_blocks
from disclosure_rag.labels.ledger import FactLedger
from disclosure_rag.retrieval.base import Retriever
from disclosure_rag.retrieval.lexical import BM25Retriever


@dataclass
class Corpus:
    """Everything the service needs to answer questions about a set of filings."""

    ledgers: dict[str, FactLedger] = field(default_factory=dict)
    chunks: list[Chunk] = field(default_factory=list)
    pdf_paths: dict[str, Path] = field(default_factory=dict)
    page_counts: dict[str, int] = field(default_factory=dict)
    retriever: Retriever = field(default_factory=BM25Retriever)

    @classmethod
    def empty(cls) -> Corpus:
        corpus = cls()
        corpus.retriever.index([])
        return corpus


def load_corpus(
    ledger_dir: Path,
    chunk_tokens: int = 600,
    overlap_tokens: int = 20,
    retriever: Retriever | None = None,
) -> Corpus:
    """Read every ledger under a directory, ingest its document, and index it.

    Defaults match the configuration the published results were measured at, so
    the running service and the benchmark are the same system.
    """
    corpus = Corpus(retriever=retriever or BM25Retriever())

    for ledger_path in sorted(ledger_dir.glob("*/ledger.json")):
        ledger = FactLedger.read(ledger_path)
        pdf_path = ledger_path.parent / "document.pdf"
        if not pdf_path.exists():
            continue

        corpus.ledgers[ledger.document_id] = ledger
        corpus.pdf_paths[ledger.document_id] = pdf_path
        corpus.page_counts[ledger.document_id] = page_count(pdf_path)
        corpus.chunks.extend(
            chunk_blocks(
                ledger.document_id,
                extract_blocks(pdf_path),
                target_tokens=chunk_tokens,
                overlap_tokens=overlap_tokens,
            )
        )

    corpus.retriever.index(corpus.chunks)
    return corpus
