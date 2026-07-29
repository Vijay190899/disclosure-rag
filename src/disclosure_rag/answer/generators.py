"""Turning retrieved passages into an answer.

Behind a protocol, with an extractive implementation that needs no API key. That
is not a placeholder: for a question whose answer is a figure printed in the
document, returning the sentence that contains it with its region outlined is
both correct and fully attributable, and it cannot hallucinate.

An LLM generator slots in for genuinely generative questions, summarising across
passages. It is a separate implementation rather than the default so the service
runs, and the whole evaluation reproduces, with no credentials and no network.
"""

from __future__ import annotations

import re
from typing import Protocol

from disclosure_rag.answer.models import Citation
from disclosure_rag.provenance import Span
from disclosure_rag.retrieval.base import ScoredChunk
from disclosure_rag.retrieval.lexical import tokenize

SENTENCE = re.compile(r"(?<=[.!?])\s+")


class Generation(Protocol):
    """A generated answer and the citations supporting it."""

    text: str
    citations: list[Citation]
    support: float


class Generator(Protocol):
    def generate(self, question: str, hits: list[ScoredChunk]) -> Generation: ...


class ExtractiveAnswer:
    """An answer quoted verbatim from a retrieved passage."""

    def __init__(self, text: str, citations: list[Citation], support: float) -> None:
        self.text = text
        self.citations = citations
        self.support = support


class ExtractiveGenerator:
    """Selects the sentence in the top passages that best answers the question.

    Support is the share of the question's content terms present in the selected
    sentence. It is a lexical overlap measure, not a model's opinion of itself,
    which means it is reproducible and cannot be confidently wrong in the way a
    self-reported confidence can.
    """

    name = "extractive"

    def __init__(self, max_passages: int = 3) -> None:
        self.max_passages = max_passages

    def generate(self, question: str, hits: list[ScoredChunk]) -> ExtractiveAnswer:
        terms = {term for term in tokenize(question) if len(term) > 3}
        if not terms or not hits:
            return ExtractiveAnswer("", [], 0.0)

        best_sentence = ""
        best_support = 0.0
        best_hit: ScoredChunk | None = None

        for hit in hits[: self.max_passages]:
            for sentence in SENTENCE.split(hit.chunk.text):
                cleaned = " ".join(sentence.split())
                if len(cleaned) < 20:
                    continue
                overlap = terms & set(tokenize(cleaned))
                support = len(overlap) / len(terms)
                if support > best_support:
                    best_support, best_sentence, best_hit = support, cleaned, hit

        if best_hit is None:
            return ExtractiveAnswer("", [], 0.0)

        by_page: dict[int, list[Span]] = {}
        for span in best_hit.chunk.spans:
            by_page.setdefault(span.page, []).append(span)
        citations = [
            Citation(
                document_id=best_hit.chunk.document_id,
                page=page,
                spans=spans,
                quote=best_sentence[:300],
                exact=False,
            )
            for page, spans in sorted(by_page.items())
        ]
        return ExtractiveAnswer(best_sentence, citations, best_support)
