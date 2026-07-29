"""The evaluation harness.

This is the one place that legitimately touches both planes: it reads gold
labels from ``disclosure_rag.labels`` and predictions from the serving plane,
and joins them. Everything else stays on one side.
"""

from disclosure_rag.evaluation.metrics import Result, StratumScore, score_run
from disclosure_rag.evaluation.questions import Question, Stratum, questions_from_ledger

__all__ = [
    "Question",
    "Result",
    "Stratum",
    "StratumScore",
    "questions_from_ledger",
    "score_run",
]
