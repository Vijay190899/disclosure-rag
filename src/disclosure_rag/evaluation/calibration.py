"""Is the confidence number worth anything?

A system that abstains has to attach a number to its answers, and the easy
mistake is to emit a score and call it a probability. Lexical overlap of 0.8 is
not "correct 80% of the time"; it is just a bigger number than 0.6. Shipping it
as though it were a probability is how a threshold ends up chosen by taste and
defended as if it were measured.

Two things are computed here.

**Expected calibration error** bins predictions by confidence and compares the
average confidence in each bin against the observed accuracy in it. A perfectly
calibrated system has ECE 0: when it says 0.7, it is right 70% of the time.

**A reliability table** shows where the error is, because a single ECE hides the
shape. Over-confidence at the top of the range is the dangerous failure for this
product, since those are the answers a reader would trust without checking.

Measured over answers the system actually gave, not over abstentions. An
abstention's confidence is a support score for a passage, not a prediction that
declining was right, so mixing the two measures nothing: a correct abstention at
confidence 0.0 would score as accuracy 1.0 and open a gap of 0.84 that says
nothing about whether the number can be trusted.

Correctness comes from the filing rather than from the model: an answer is right
when it matches the tagged value. Answering a question that had no answer counts
as wrong whatever value came back, because it is.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Bin(BaseModel):
    """One confidence band."""

    model_config = {"frozen": True}

    lower: float
    upper: float
    count: int
    mean_confidence: float
    accuracy: float

    @property
    def gap(self) -> float:
        """Positive means over-confident, which is the direction that costs trust."""
        return self.mean_confidence - self.accuracy


class Calibration(BaseModel):
    """How well a confidence number predicts being right."""

    samples: int = 0
    expected_calibration_error: float = Field(
        default=0.0, description="Weighted mean gap between confidence and accuracy"
    )
    max_calibration_error: float = Field(
        default=0.0, description="Worst single bin, which one average can hide"
    )
    overconfidence: float = Field(
        default=0.0,
        description="Weighted mean of confidence above accuracy, counting only that direction",
    )
    bins: list[Bin] = Field(default_factory=list)


def calibrate(predictions: list[tuple[float, bool]], bin_count: int = 10) -> Calibration:
    """Bin (confidence, was_correct) pairs and measure the gap in each.

    Empty bins are dropped rather than reported as perfectly calibrated, which
    is what counting them as zero error would quietly do.
    """
    if not predictions:
        return Calibration()

    edges = [index / bin_count for index in range(bin_count + 1)]
    bins: list[Bin] = []
    total = len(predictions)
    ece = 0.0
    overconfidence = 0.0
    worst = 0.0

    for index in range(bin_count):
        lower, upper = edges[index], edges[index + 1]
        # Upper edge inclusive on the last bin so confidence 1.0 is counted.
        members = [
            (confidence, correct)
            for confidence, correct in predictions
            if lower <= confidence < upper or (index == bin_count - 1 and confidence == upper)
        ]
        if not members:
            continue

        mean_confidence = sum(confidence for confidence, _ in members) / len(members)
        accuracy = sum(1 for _, correct in members if correct) / len(members)
        weight = len(members) / total
        gap = abs(mean_confidence - accuracy)

        ece += weight * gap
        overconfidence += weight * max(mean_confidence - accuracy, 0.0)
        worst = max(worst, gap)
        bins.append(
            Bin(
                lower=lower,
                upper=upper,
                count=len(members),
                mean_confidence=round(mean_confidence, 4),
                accuracy=round(accuracy, 4),
            )
        )

    return Calibration(
        samples=total,
        expected_calibration_error=round(ece, 4),
        max_calibration_error=round(worst, 4),
        overconfidence=round(overconfidence, 4),
        bins=bins,
    )


def render_calibration(calibration: Calibration) -> str:
    if not calibration.bins:
        return "\nCalibration: no predictions\n"
    lines = [
        "",
        f"Calibration on {calibration.samples} answers: "
        f"ECE {calibration.expected_calibration_error:.3f}, "
        f"max bin error {calibration.max_calibration_error:.3f}, "
        f"over-confidence {calibration.overconfidence:.3f}",
        "",
        "| Confidence band | n | mean confidence | accuracy | gap |",
        "|---|---|---|---|---|",
    ]
    lines.extend(
        f"| {item.lower:.1f} to {item.upper:.1f} | {item.count} | "
        f"{item.mean_confidence:.3f} | {item.accuracy:.3f} | {item.gap:+.3f} |"
        for item in calibration.bins
    )
    return "\n".join(lines)
