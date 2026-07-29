"""BM25 lexical retrieval. The baseline everything else has to beat.

Deliberately the first thing built, and deliberately dependency-free: no model
download, no vector database, no network. That matters for a benchmark, because
a baseline nobody can reproduce is not much of a baseline. It is also fast
enough that a full evaluation run costs seconds, which is what makes the
ablation ladder in ADR-0006 practical rather than aspirational.

The roadmap originally called for a dense-only baseline first, with lexical
added on top as the second rung. That was the wrong order. A baseline should be
the simplest system that works, and this is simpler than anything involving an
embedding model. Dense retrieval becomes the next delta row instead.

Standard Okapi BM25. The tokenizer is deliberately naive, which is itself part
of the measurement: risk R3 is that German compound nouns break lexical
matching, and a naive tokenizer is exactly what that risk describes. Measuring
it needs the naive version first.
"""

from __future__ import annotations

import math
import re
from collections import Counter

from disclosure_rag.ingest.chunker import Chunk
from disclosure_rag.retrieval.base import ScoredChunk

# Keeps digits, separators inside numbers, and letters including umlauts.
TOKEN = re.compile(r"[^\W_]+(?:[.,][^\W_]+)*", re.UNICODE)

K1 = 1.5
B = 0.75


def tokenize(text: str) -> list[str]:
    """Lowercase word and number tokens.

    Numbers keep their separators, so "5.996,4" stays one token rather than
    becoming three. That matters here: exact figures and identifiers are the
    reason lexical retrieval is expected to help at all.
    """
    return [match.group().lower() for match in TOKEN.finditer(text)]


class BM25Retriever:
    """In-memory BM25 over chunk text."""

    name = "bm25"

    def __init__(self, k1: float = K1, b: float = B) -> None:
        self.k1 = k1
        self.b = b
        self._chunks: list[Chunk] = []
        self._term_frequencies: list[Counter[str]] = []
        self._lengths: list[int] = []
        self._document_frequency: Counter[str] = Counter()
        self._average_length = 0.0

    def index(self, chunks: list[Chunk]) -> None:
        self._chunks = list(chunks)
        self._term_frequencies = []
        self._lengths = []
        self._document_frequency = Counter()

        for chunk in self._chunks:
            tokens = tokenize(chunk.text)
            counts = Counter(tokens)
            self._term_frequencies.append(counts)
            self._lengths.append(len(tokens))
            self._document_frequency.update(counts.keys())

        self._average_length = sum(self._lengths) / len(self._lengths) if self._lengths else 0.0

    def _idf(self, term: str) -> float:
        total = len(self._chunks)
        seen = self._document_frequency.get(term, 0)
        # Standard BM25 idf with the +1 that keeps it non-negative for terms
        # appearing in most documents.
        return math.log(1 + (total - seen + 0.5) / (seen + 0.5))

    def search(self, query: str, top_k: int = 10) -> list[ScoredChunk]:
        if not self._chunks:
            return []

        query_terms = tokenize(query)
        scored: list[tuple[float, int]] = []

        for position, counts in enumerate(self._term_frequencies):
            length = self._lengths[position]
            score = 0.0
            for term in query_terms:
                frequency = counts.get(term, 0)
                if not frequency:
                    continue
                denominator = frequency + self.k1 * (
                    1 - self.b + self.b * length / (self._average_length or 1.0)
                )
                score += self._idf(term) * frequency * (self.k1 + 1) / denominator
            if score > 0:
                scored.append((score, position))

        # Sort by score, then by position, so ties resolve the same way on every
        # run. A benchmark whose ordering wobbles is not reproducible.
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        return [
            ScoredChunk(chunk=self._chunks[position], score=score)
            for score, position in scored[:top_k]
        ]
