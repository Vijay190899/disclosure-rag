"""Answering: route a question, answer it, and cite where the answer came from.

Two paths, because financial documents carry two kinds of content.

A figure that the filer has tagged has an exact answer and an exact location.
Sending that through a vector search and asking a model to read it back is
strictly worse than looking it up: it can be wrong, and its citation is a
prediction rather than a fact. So tagged figures are answered from the
structured layer.

Everything else, the narrative and qualitative content, is what retrieval is
for.
"""

from disclosure_rag.answer.models import Answer, Citation, Route
from disclosure_rag.answer.pipeline import AnswerPipeline
from disclosure_rag.answer.router import ConceptIndex, RoutingDecision, route_question

__all__ = [
    "Answer",
    "AnswerPipeline",
    "Citation",
    "ConceptIndex",
    "Route",
    "RoutingDecision",
    "route_question",
]
