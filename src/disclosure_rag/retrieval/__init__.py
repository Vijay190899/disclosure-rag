"""Retrieval. The other half of the system under test.

Nothing here may import from ``disclosure_rag.labels``: this is what the
benchmark measures, so it must not be able to see the answer key.
"""

from disclosure_rag.retrieval.base import Retriever, ScoredChunk
from disclosure_rag.retrieval.lexical import BM25Retriever, tokenize

__all__ = ["BM25Retriever", "Retriever", "ScoredChunk", "tokenize"]
