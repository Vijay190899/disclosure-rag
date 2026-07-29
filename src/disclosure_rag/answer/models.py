"""The response contract.

Stable and versioned: the viewer, the evaluation harness and any client all read
these shapes, so changing them is a breaking change.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from disclosure_rag.provenance import Span


class Route(StrEnum):
    """Which mechanism answered the question."""

    LEDGER = "ledger"
    PASSAGE = "passage"
    NONE = "none"


class Status(StrEnum):
    ANSWERED = "answered"
    ABSTAINED = "abstained"


class Citation(BaseModel):
    """Where an answer came from, precisely enough to check in one click."""

    model_config = {"frozen": True}

    document_id: str
    page: int
    spans: list[Span] = Field(
        description="Regions to outline. A list because a table can span a page break."
    )
    quote: str = Field(default="", description="The text at those regions")
    exact: bool = Field(
        default=False,
        description=(
            "True when the location is the filer's own tag rather than a prediction. "
            "Exact citations are not estimated and are not scored as if they were."
        ),
    )


class Answer(BaseModel):
    """A complete response."""

    question: str
    status: Status
    route: Route
    text: str = ""
    value: str | None = Field(default=None, description="Normalised figure, when applicable")
    unit: str | None = None
    period: str | None = None
    citations: list[Citation] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = Field(default="", description="Why it abstained, when it did")
    timings_ms: dict[str, float] = Field(default_factory=dict)

    @property
    def answered(self) -> bool:
        return self.status is Status.ANSWERED
