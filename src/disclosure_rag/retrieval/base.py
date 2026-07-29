"""The retrieval contract.

A protocol rather than a base class, so a dense retriever, a hybrid one, or a
reranked one can be measured against the same question set without any of them
knowing about each other. Principle P6.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from disclosure_rag.ingest.chunker import Chunk
from disclosure_rag.provenance import Span


class ScoredChunk(BaseModel):
    """A retrieved chunk and its score."""

    model_config = {"frozen": True}

    chunk: Chunk
    score: float

    @property
    def spans(self) -> list[Span]:
        """The regions this result would cite."""
        return self.chunk.spans


class Retriever(Protocol):
    """Anything that can return ranked chunks for a query."""

    name: str

    def index(self, chunks: list[Chunk]) -> None:
        """Build or rebuild the index. Replaces any previous contents."""
        ...

    def search(self, query: str, top_k: int = 10) -> list[ScoredChunk]:
        """Return the top ranked chunks, best first."""
        ...
