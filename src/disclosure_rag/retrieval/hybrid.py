"""Hybrid retrieval by reciprocal rank fusion.

This is the decision recorded in DECISIONS.md on 2026-07-07, and the one I have
been most confident about and least able to justify: dense vectors under-retrieve
exact figures and identifiers, lexical matching catches them, so fusing the two
should beat either. It has been labelled a hypothesis ever since. This module is
what turns it into a row in the table.

Fusion is by rank rather than by score. BM25 scores are unbounded and cosine
similarities sit in a narrow band, so combining them numerically means inventing
a normalisation and then defending it. Reciprocal rank fusion needs no such
choice: it uses only the ordering each retriever produced, which is the part
they actually agree on the meaning of.

    score(chunk) = sum over retrievers of 1 / (k + rank)

``k`` damps the influence of top ranks. 60 is the value from the original paper
and is used here rather than tuned, because tuning it against the same question
set the result is reported on would be fitting the benchmark.
"""

from __future__ import annotations

from disclosure_rag.ingest.chunker import Chunk
from disclosure_rag.retrieval.base import Retriever, ScoredChunk

RRF_K = 60

# Candidates are pulled deeper than the reported top_k so fusion has something to
# work with: a chunk ranked eighth by one retriever and ninth by the other should
# be able to reach the top of the fused list.
CANDIDATE_DEPTH = 50


class HybridRetriever:
    """Reciprocal rank fusion over any number of retrievers."""

    def __init__(self, retrievers: list[Retriever], k: int = RRF_K) -> None:
        if not retrievers:
            raise ValueError("hybrid retrieval needs at least one retriever")
        self.retrievers = retrievers
        self.k = k
        self.name = "hybrid(" + "+".join(r.name for r in retrievers) + ")"

    def index(self, chunks: list[Chunk]) -> None:
        """Index each member, skipping any that already hold these chunks.

        A member can be shared with an earlier rung of an ablation ladder, and
        re-indexing it would re-embed the whole corpus for no gain.
        """
        for retriever in self.retrievers:
            existing = getattr(retriever, "_chunks", None)
            if existing is not None and len(existing) == len(chunks):
                continue
            retriever.index(chunks)

    def search(
        self, query: str, top_k: int = 10, document_id: str | None = None
    ) -> list[ScoredChunk]:
        fused: dict[str, float] = {}
        seen: dict[str, Chunk] = {}

        for retriever in self.retrievers:
            candidates = retriever.search(query, top_k=CANDIDATE_DEPTH, document_id=document_id)
            for rank, hit in enumerate(candidates, start=1):
                chunk_id = hit.chunk.chunk_id
                seen.setdefault(chunk_id, hit.chunk)
                fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (self.k + rank)

        ranked = sorted(fused.items(), key=lambda pair: (-pair[1], pair[0]))
        return [
            ScoredChunk(chunk=seen[chunk_id], score=score) for chunk_id, score in ranked[:top_k]
        ]
