"""Provenance types.

Section 6 of the technical documentation and ADR-0004 make this the contract
everything downstream couples to, so it lives on its own with no dependencies on
the rest of the package.

Two rules are enforced here rather than left to convention:

- Coordinates are normalised to the page box, so a change of render resolution
  does not invalidate a stored index.
- Anything that has a location carries a *list* of spans. A table continuing
  across a page break occupies regions on two pages, and that is the motivating
  example rather than an edge case.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class Span(BaseModel):
    """A rectangular region on one page, normalised to the page box.

    Coordinates run from 0 to 1 with the origin at the top left, matching PDF
    viewer convention rather than mathematical convention.
    """

    model_config = {"frozen": True}

    page: int = Field(ge=0, description="Zero-based page index")
    x0: float = Field(ge=0.0, le=1.0)
    y0: float = Field(ge=0.0, le=1.0)
    x1: float = Field(ge=0.0, le=1.0)
    y1: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _ordered(self) -> Span:
        if self.x1 < self.x0 or self.y1 < self.y0:
            raise ValueError(f"span corners are inverted: {self.x0, self.y0, self.x1, self.y1}")
        return self

    @classmethod
    def from_rect(
        cls, page: int, x0: float, y0: float, x1: float, y1: float, width: float, height: float
    ) -> Span:
        """Build a span from absolute coordinates and the page dimensions."""
        if width <= 0 or height <= 0:
            raise ValueError("page dimensions must be positive")
        return cls(
            page=page,
            x0=min(max(x0 / width, 0.0), 1.0),
            y0=min(max(y0 / height, 0.0), 1.0),
            x1=min(max(x1 / width, 0.0), 1.0),
            y1=min(max(y1 / height, 0.0), 1.0),
        )

    @property
    def area(self) -> float:
        return (self.x1 - self.x0) * (self.y1 - self.y0)

    def iou(self, other: Span) -> float:
        """Intersection over union, the metric citation accuracy is scored with.

        Zero for spans on different pages: a box in the right place on the wrong
        page is wrong, and averaging it as a partial credit would hide exactly
        the failure this project is built to detect.
        """
        if self.page != other.page:
            return 0.0
        x0, y0 = max(self.x0, other.x0), max(self.y0, other.y0)
        x1, y1 = min(self.x1, other.x1), min(self.y1, other.y1)
        if x1 <= x0 or y1 <= y0:
            return 0.0
        intersection = (x1 - x0) * (y1 - y0)
        union = self.area + other.area - intersection
        return intersection / union if union > 0 else 0.0


def best_iou(predicted: Span, gold: list[Span]) -> float:
    """Score one predicted span against whichever gold span it best matches."""
    return max((predicted.iou(candidate) for candidate in gold), default=0.0)


def union_on_page(spans: list[Span]) -> Span | None:
    """Bounding box of spans that share a page, for display only.

    Never persisted. ADR-0004 keeps span lists unflattened in storage and in the
    API; this exists because a viewer sometimes needs one rectangle to draw.
    """
    if not spans:
        return None
    pages = {span.page for span in spans}
    if len(pages) != 1:
        raise ValueError(f"cannot union spans across pages {sorted(pages)}")
    return Span(
        page=spans[0].page,
        x0=min(s.x0 for s in spans),
        y0=min(s.y0 for s in spans),
        x1=max(s.x1 for s in spans),
        y1=max(s.y1 for s in spans),
    )
