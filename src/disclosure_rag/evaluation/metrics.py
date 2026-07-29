"""Scoring.

Two things are measured, and the difference between them is the point.

**Recall@k** asks whether the right passage came back anywhere in the top k.
Every RAG project reports some version of this.

**Citation coverage@1** asks whether the region the reader is actually shown
contains the answer. A system can retrieve the right passage at rank three and
still point somewhere unhelpful at rank one, which is what a reader sees. That
gap is what this project exists to expose, and almost nobody publishes it.

A note on why this is coverage and not IoU, because the first version got it
wrong. IoU compares two regions of comparable size. Here they are not: a gold
fact is a number occupying roughly 0.03% of a page, and a citation is the text
block containing it, about 1.7%. Their IoU sits near 0.01 even when the citation
is perfectly correct, so thresholding IoU measures the size difference rather
than the quality of the citation. The first run scored 0.000 across the board
for exactly that reason, and it was a broken metric rather than a broken
retriever: the same run scores 60 of 60 under containment.

**Tightness** is reported alongside, because coverage alone can be gamed by
citing more. Citing a whole page always contains the answer and helps nobody.
Tightness is the share of the cited region that is actually the answer, so it
starts low with block-level citations and rises as citations get finer. Together
the pair says "it points at the right place, and here is how precisely".

Note that ``recall_at_1`` and ``citation_coverage_at_1`` are the same quantity
by construction: both ask whether the top result contains the gold region. Both
are reported because they answer different questions in a reader's head, but the
informative comparison is **recall@5 against coverage@1**. The difference between
them is the share of questions where the system had the answer in hand and
showed something else first.

``shown_first_when_found`` states that directly: of the questions where the
answer was retrieved anywhere in the top ten, how often was it ranked first.
That is the number this project is really about.

All of these are deterministic functions of the index and the question set, so
they can gate CI without a model call. ADR-0006.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from disclosure_rag.evaluation.questions import Question, Stratum
from disclosure_rag.provenance import Span, best_coverage, best_iou

# A citation counts as correct when it contains at least this much of the gold
# region. Not 1.0, because a fact box can straddle a block boundary by a pixel.
COVERAGE_THRESHOLD = 0.5

# Predicted figure against tagged figure, both number-sized, so IoU is fair here.
IOU_THRESHOLD = 0.5


class Result(BaseModel):
    """What a retriever returned for one question."""

    model_config = {"frozen": True}

    question_id: str
    stratum: Stratum
    retrieved_spans: list[list[Span]] = Field(
        default_factory=list,
        description="Block-level spans per retrieved chunk, best first",
    )
    cited_spans: list[Span] = Field(
        default_factory=list,
        description="The figures the top result would actually outline for a reader",
    )

    def hit_rank(self, gold: list[Span], threshold: float = COVERAGE_THRESHOLD) -> int | None:
        """Rank of the first retrieved chunk whose region contains a gold span."""
        for rank, spans in enumerate(self.retrieved_spans, start=1):
            if best_coverage(gold, spans) >= threshold:
                return rank
        return None

    def top_coverage(self, gold: list[Span]) -> float:
        """How much of the gold region the top-ranked result contains.

        Scored against the first result only, deliberately. That is what a
        reader would be shown, so crediting the best of ten would flatter the
        system with a region it never displayed.
        """
        if not self.retrieved_spans:
            return 0.0
        return best_coverage(gold, self.retrieved_spans[0])

    def top_tightness(self, gold: list[Span]) -> float:
        """Share of the cited region that is the answer, for the top result."""
        if not self.retrieved_spans:
            return 0.0
        best = 0.0
        for span in self.retrieved_spans[0]:
            for target in gold:
                if span.covers(target) >= COVERAGE_THRESHOLD:
                    best = max(best, span.tightness(target))
        return best

    def citation_iou(self, gold: list[Span]) -> float:
        """Overlap between the figure this would outline and the tagged figure.

        This is the metric the project exists to report, and it only became
        meaningful once citations were narrowed from a text block to a number.
        Block against number gives an IoU near 0.015 even when perfectly correct,
        so the threshold measured the size difference; number against number
        makes the comparison fair. See citation.py.
        """
        return max(
            (best_iou(span, gold) for span in self.cited_spans),
            default=0.0,
        )


class StratumScore(BaseModel):
    """Scores for one stratum. Never combined across strata."""

    stratum: Stratum
    questions: int = 0
    recall_at_1: float = 0.0
    recall_at_5: float = 0.0
    recall_at_10: float = 0.0
    citation_coverage_at_1: float = Field(
        default=0.0,
        description="Share of questions whose top result contains the gold region",
    )
    shown_first_when_found: float = Field(
        default=0.0,
        description="Of questions where the answer was retrieved at all, share shown at rank 1",
    )
    mean_tightness: float = Field(
        default=0.0,
        description="Share of the cited block that is the answer, where correct",
    )
    citation_iou_at_50: float = Field(
        default=0.0,
        description="Share of questions whose cited figure overlaps the tagged figure by >= 0.5",
    )
    mean_citation_iou: float = 0.0
    citation_iou_given_rank_1: float = Field(
        default=0.0,
        description=(
            "Citation IoU@0.5 among questions where the top passage was already correct. "
            "Isolates the figure-selection problem from the retrieval problem."
        ),
    )
    questions_at_rank_1: int = 0


def _recall_at(paired: list[tuple[Result, list[Span]]], k: int) -> float:
    if not paired:
        return 0.0
    hits = sum(
        1 for result, gold in paired if (rank := result.hit_rank(gold)) is not None and rank <= k
    )
    return hits / len(paired)


def score_run(questions: list[Question], results: dict[str, Result]) -> list[StratumScore]:
    """Score a run, one row per stratum.

    A question with no result counts as a miss rather than being dropped.
    Silently skipping unanswered questions would let a retriever raise its score
    by returning nothing.
    """
    scores: list[StratumScore] = []

    for stratum in Stratum:
        paired: list[tuple[Result, list[Span]]] = []
        for question in questions:
            if question.stratum != stratum:
                continue
            result = results.get(
                question.question_id,
                Result(question_id=question.question_id, stratum=stratum),
            )
            paired.append((result, question.gold_spans))

        if not paired:
            continue

        coverages = [result.top_coverage(gold) for result, gold in paired]
        correct = [
            result.top_tightness(gold)
            for result, gold in paired
            if result.top_coverage(gold) >= COVERAGE_THRESHOLD
        ]
        citation_ious = [result.citation_iou(gold) for result, gold in paired]
        # Citation accuracy cannot exceed rank-1 recall: with the wrong passage on
        # top there is nothing correct to outline. Reporting it conditionally
        # separates "found the right place" from "pointed at the right thing in
        # it", which are different failures with different fixes.
        conditional = [
            result.citation_iou(gold) for result, gold in paired if result.hit_rank(gold) == 1
        ]
        at_1, at_10 = _recall_at(paired, 1), _recall_at(paired, 10)
        scores.append(
            StratumScore(
                stratum=stratum,
                questions=len(paired),
                recall_at_1=at_1,
                recall_at_5=_recall_at(paired, 5),
                recall_at_10=at_10,
                shown_first_when_found=at_1 / at_10 if at_10 else 0.0,
                citation_coverage_at_1=sum(1 for value in coverages if value >= COVERAGE_THRESHOLD)
                / len(coverages),
                mean_tightness=sum(correct) / len(correct) if correct else 0.0,
                citation_iou_at_50=sum(1 for value in citation_ious if value >= IOU_THRESHOLD)
                / len(citation_ious),
                mean_citation_iou=sum(citation_ious) / len(citation_ious),
                citation_iou_given_rank_1=(
                    sum(1 for v in conditional if v >= IOU_THRESHOLD) / len(conditional)
                    if conditional
                    else 0.0
                ),
                questions_at_rank_1=len(conditional),
            )
        )

    return scores
