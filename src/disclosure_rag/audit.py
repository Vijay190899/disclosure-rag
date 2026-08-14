"""An append-only record of every answer, and the ability to prove it again.

The product claim is that a reader can verify an answer. That claim has a second
half nobody usually builds: the answer has to still be verifiable later, when the
filing has been amended, the index rebuilt and the settings changed.

So every answer is recorded with the snapshot it was produced against, and any
record can be replayed. Replay re-runs the same question through the current
pipeline and reports whether it still produces the same answer, or why not. Three
outcomes, and the middle one is the point:

- **reproduced**: same corpus, same answer. The record is evidence.
- **superseded**: the corpus or settings have moved on, so the record describes
  something the system no longer is. Not a failure, a fact, and one an auditor
  needs stated rather than hidden.
- **diverged**: same snapshot, different answer. That is a bug, and it is the
  only outcome that should ever be alarming.

Written as JSONL, appended, never rewritten. A log you can edit is not a log.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field

from disclosure_rag.answer.models import Answer
from disclosure_rag.versioning import Snapshot, hash_text


class ReplayOutcome(StrEnum):
    REPRODUCED = "reproduced"
    SUPERSEDED = "superseded"
    DIVERGED = "diverged"


class AuditRecord(BaseModel):
    """One answer, and everything needed to reproduce or supersede it."""

    model_config = {"frozen": True}

    record_id: str
    recorded_at: str
    question: str
    document_id: str
    snapshot_id: str
    document_version: str = Field(description="Content hash of the filing as it was then")
    pipeline_version: str
    answer: Answer

    @classmethod
    def create(
        cls, question: str, document_id: str, answer: Answer, snapshot: Snapshot
    ) -> AuditRecord:
        recorded_at = datetime.now(UTC).isoformat()
        # Derived from content, so the same answer recorded twice is detectable
        # and the id cannot drift from what it identifies.
        record_id = hash_text(f"{snapshot.snapshot_id}|{document_id}|{question}|{recorded_at}")[:16]
        return cls(
            record_id=record_id,
            recorded_at=recorded_at,
            question=question,
            document_id=document_id,
            snapshot_id=snapshot.snapshot_id,
            document_version=snapshot.version_of(document_id),
            pipeline_version=snapshot.pipeline_version,
            answer=answer,
        )


class ReplayResult(BaseModel):
    """What happened when a record was replayed."""

    model_config = {"frozen": True}

    record_id: str
    outcome: ReplayOutcome
    detail: str = ""
    recorded_answer: str = ""
    current_answer: str = ""


class AuditLog:
    """Append-only JSONL, safe to write from several request handlers."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def append(self, record: AuditRecord) -> AuditRecord:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = record.model_dump_json()
        with self._lock, self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        return record

    def __iter__(self) -> Iterator[AuditRecord]:
        if not self.path.exists():
            return
        with self.path.open(encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if stripped:
                    yield AuditRecord.model_validate_json(stripped)

    def get(self, record_id: str) -> AuditRecord | None:
        for record in self:
            if record.record_id == record_id:
                return record
        return None

    def __len__(self) -> int:
        return sum(1 for _ in self)


def _comparable(answer: Answer) -> str:
    """The parts of an answer that must not change for a given corpus.

    Timings are excluded deliberately: they vary run to run and comparing them
    would report every replay as a divergence, which trains people to ignore the
    one signal that should never be ignored.
    """
    citations = [
        {
            "document_id": citation.document_id,
            "page": citation.page,
            "spans": [span.model_dump() for span in citation.spans],
            "exact": citation.exact,
        }
        for citation in answer.citations
    ]
    return json.dumps(
        {
            "status": answer.status.value,
            "route": answer.route.value,
            "text": answer.text,
            "value": answer.value,
            "unit": answer.unit,
            "period": answer.period,
            "confidence": answer.confidence,
            "citations": citations,
        },
        sort_keys=True,
    )


def replay(record: AuditRecord, pipeline: object, snapshot: Snapshot) -> ReplayResult:
    """Re-run a recorded answer and report whether it still holds."""
    from disclosure_rag.answer.pipeline import AnswerPipeline

    assert isinstance(pipeline, AnswerPipeline)

    if record.snapshot_id != snapshot.snapshot_id:
        current = snapshot.version_of(record.document_id)
        if not current:
            detail = f"{record.document_id} is no longer in the corpus"
        elif current != record.document_version:
            detail = (
                f"the filing has changed since this answer: "
                f"{record.document_version[:12]} then, {current[:12]} now"
            )
        else:
            detail = "the corpus or index settings have changed, this filing has not"
        return ReplayResult(
            record_id=record.record_id, outcome=ReplayOutcome.SUPERSEDED, detail=detail
        )

    fresh = pipeline.answer(record.question, record.document_id)
    recorded, current = _comparable(record.answer), _comparable(fresh)
    if recorded == current:
        return ReplayResult(
            record_id=record.record_id,
            outcome=ReplayOutcome.REPRODUCED,
            detail="same snapshot, same answer",
            recorded_answer=record.answer.text,
            current_answer=fresh.text,
        )
    return ReplayResult(
        record_id=record.record_id,
        outcome=ReplayOutcome.DIVERGED,
        detail="the snapshot is unchanged but the answer is not, which is a defect",
        recorded_answer=record.answer.text,
        current_answer=fresh.text,
    )
