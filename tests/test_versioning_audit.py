"""Tests for corpus versioning and the replayable audit record."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from disclosure_rag.answer.models import Answer, Route, Status
from disclosure_rag.answer.pipeline import AnswerPipeline
from disclosure_rag.audit import AuditLog, AuditRecord, ReplayOutcome, replay
from disclosure_rag.ingest.chunker import Chunk
from disclosure_rag.labels.facts import Fact
from disclosure_rag.labels.ledger import FactLedger, LocatedFact
from disclosure_rag.provenance import Span
from disclosure_rag.retrieval.lexical import BM25Retriever
from disclosure_rag.versioning import (
    IndexSettings,
    Snapshot,
    hash_file,
    hash_text,
    label_plane_version,
)

SETTINGS = IndexSettings(chunk_tokens=600, overlap_tokens=20, retriever="bm25")
GOLD = Span(page=25, x0=0.63, y0=0.07, x1=0.66, y1=0.08)


def snapshot(documents: dict[str, str], settings: IndexSettings = SETTINGS) -> Snapshot:
    return Snapshot.build(documents, settings)


def test_the_same_corpus_yields_the_same_snapshot_id() -> None:
    assert (
        snapshot({"a": "h1", "b": "h2"}).snapshot_id == snapshot({"a": "h1", "b": "h2"}).snapshot_id
    )


def test_load_order_does_not_change_the_snapshot_id() -> None:
    """An id that changes when nothing did teaches people to ignore it."""
    assert (
        snapshot({"a": "h1", "b": "h2"}).snapshot_id == snapshot({"b": "h2", "a": "h1"}).snapshot_id
    )


def test_an_amended_filing_changes_the_snapshot() -> None:
    assert snapshot({"a": "h1"}).snapshot_id != snapshot({"a": "amended"}).snapshot_id


def test_adding_a_filing_changes_the_snapshot() -> None:
    assert snapshot({"a": "h1"}).snapshot_id != snapshot({"a": "h1", "b": "h2"}).snapshot_id


def test_rechunking_changes_the_snapshot() -> None:
    """Settings decide what the index contains, so they belong in the identity."""
    other = IndexSettings(chunk_tokens=200, overlap_tokens=20, retriever="bm25")
    assert snapshot({"a": "h1"}).snapshot_id != snapshot({"a": "h1"}, other).snapshot_id


def test_changing_the_retriever_changes_the_snapshot() -> None:
    other = IndexSettings(chunk_tokens=600, overlap_tokens=20, retriever="dense:e5")
    assert snapshot({"a": "h1"}).snapshot_id != snapshot({"a": "h1"}, other).snapshot_id


def test_a_file_hash_follows_its_contents(tmp_path: Path) -> None:
    path = tmp_path / "report.xhtml"
    path.write_text("original", encoding="utf-8")
    first = hash_file(path)
    path.write_text("amended", encoding="utf-8")
    assert hash_file(path) != first
    assert first == hash_text("original")


def build_pipeline(value: str = "5996400000") -> tuple[AnswerPipeline, Snapshot]:
    fact = Fact(
        fact_id="f1",
        concept="ifrs-full:Assets",
        displayed="5.996,4",
        value=Decimal(value),
        unit="EUR",
        period="instant:2022-12-31",
    )
    ledger = FactLedger(
        document_id="doc",
        content_hash="hash-of-the-filing",
        facts=[LocatedFact(fact=fact, span=GOLD)],
        concept_labels={"ifrs-full:Assets": "Bilanzsumme"},
    )
    retriever = BM25Retriever()
    retriever.index(
        [
            Chunk(
                chunk_id="c0",
                document_id="doc",
                text="Das Kreditportfolio unterliegt einem Ausfallrisiko.",
                spans=[Span(page=1, x0=0.1, y0=0.2, x1=0.9, y1=0.3)],
                order=0,
            )
        ]
    )
    current = snapshot({"doc": ledger.content_hash})
    pipeline = AnswerPipeline({"doc": ledger}, retriever, snapshot_id=current.snapshot_id)
    return pipeline, current


QUESTION = "Wie hoch war Bilanzsumme zum 31.12.2022?"


def test_an_answer_carries_the_snapshot_it_was_produced_against() -> None:
    pipeline, current = build_pipeline()
    answer = pipeline.answer(QUESTION, "doc")
    assert answer.snapshot_id == current.snapshot_id


def test_an_unchanged_corpus_reproduces_the_answer() -> None:
    pipeline, current = build_pipeline()
    answer = pipeline.answer(QUESTION, "doc")
    record = AuditRecord.create(QUESTION, "doc", answer, current)

    result = replay(record, pipeline, current)
    assert result.outcome is ReplayOutcome.REPRODUCED


def test_an_amended_filing_supersedes_the_record() -> None:
    """Not a failure. A fact an auditor needs stated rather than hidden."""
    pipeline, current = build_pipeline()
    record = AuditRecord.create(QUESTION, "doc", pipeline.answer(QUESTION, "doc"), current)

    amended = snapshot({"doc": "a-different-filing"})
    result = replay(record, pipeline, amended)
    assert result.outcome is ReplayOutcome.SUPERSEDED
    assert "the filing has changed" in result.detail


def test_a_removed_document_supersedes_the_record() -> None:
    pipeline, current = build_pipeline()
    record = AuditRecord.create(QUESTION, "doc", pipeline.answer(QUESTION, "doc"), current)

    result = replay(record, pipeline, snapshot({"other": "h"}))
    assert result.outcome is ReplayOutcome.SUPERSEDED
    assert "no longer in the corpus" in result.detail


def test_rechunking_supersedes_the_record_without_blaming_the_filing() -> None:
    pipeline, current = build_pipeline()
    record = AuditRecord.create(QUESTION, "doc", pipeline.answer(QUESTION, "doc"), current)

    rechunked = snapshot(
        {"doc": "hash-of-the-filing"},
        IndexSettings(chunk_tokens=200, overlap_tokens=20, retriever="bm25"),
    )
    result = replay(record, pipeline, rechunked)
    assert result.outcome is ReplayOutcome.SUPERSEDED
    assert "this filing has not" in result.detail


def test_a_changed_answer_on_an_unchanged_snapshot_is_a_divergence() -> None:
    """The only outcome that should ever be alarming."""
    pipeline, current = build_pipeline()
    record = AuditRecord.create(QUESTION, "doc", pipeline.answer(QUESTION, "doc"), current)

    # Same snapshot id, different underlying value: a defect, not a corpus change.
    tampered, _ = build_pipeline(value="999")
    tampered.snapshot_id = current.snapshot_id

    result = replay(record, tampered, current)
    assert result.outcome is ReplayOutcome.DIVERGED
    assert result.recorded_answer != result.current_answer


def test_timings_do_not_count_as_a_divergence() -> None:
    """Comparing them would flag every replay and train people to ignore the signal."""
    pipeline, current = build_pipeline()
    answer = pipeline.answer(QUESTION, "doc")
    slowed = answer.model_copy(update={"timings_ms": {"route": 999.0, "ledger": 999.0}})
    record = AuditRecord.create(QUESTION, "doc", slowed, current)

    assert replay(record, pipeline, current).outcome is ReplayOutcome.REPRODUCED


def test_the_log_appends_and_reads_back(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.jsonl")
    pipeline, current = build_pipeline()

    first = log.append(
        AuditRecord.create(QUESTION, "doc", pipeline.answer(QUESTION, "doc"), current)
    )
    log.append(
        AuditRecord.create(
            "another question",
            "doc",
            Answer(question="another question", status=Status.ABSTAINED, route=Route.PASSAGE),
            current,
        )
    )

    assert len(log) == 2
    restored = log.get(first.record_id)
    assert restored is not None
    assert restored.question == QUESTION
    assert restored.document_version == "hash-of-the-filing"


def test_an_unknown_record_id_reads_as_none(tmp_path: Path) -> None:
    assert AuditLog(tmp_path / "audit.jsonl").get("absent") is None


def test_a_missing_log_file_is_empty_rather_than_an_error(tmp_path: Path) -> None:
    assert len(AuditLog(tmp_path / "never-written.jsonl")) == 0


def test_a_rebuild_skips_a_filing_whose_content_has_not_changed(tmp_path: Path) -> None:
    """Building renders twice with a browser, so a nightly job must not redo it."""
    from disclosure_rag.labels.build import build_one

    filing = tmp_path / "filings" / "doc"
    filing.mkdir(parents=True)
    report = filing / "report.xhtml"
    report.write_text("<html><body>nothing tagged</body></html>", encoding="utf-8")

    out = tmp_path / "ledgers"
    work = out / "doc"
    work.mkdir(parents=True)
    FactLedger(
        document_id="doc",
        content_hash=hash_file(report),
        builder_version=label_plane_version(),
    ).write(work / "ledger.json")
    (work / "document.pdf").write_bytes(b"%PDF-1.4 stub")

    # No browser is launched: the skip happens before any rendering.
    result = build_one(report, out)
    assert result.content_hash == hash_file(report)


def test_a_ledger_built_by_older_code_is_not_skipped(tmp_path: Path) -> None:
    """The content hash alone is not enough to say a ledger is current.

    Changing how facts are extracted leaves every ledger stale while the source
    filings are untouched. Keyed on content alone, the builder reports
    "unchanged, skipping" and produces nothing, which is the worst kind of wrong
    because it reads as success.
    """
    from disclosure_rag.labels.build import build_one

    filing = tmp_path / "filings" / "doc"
    filing.mkdir(parents=True)
    report = filing / "report.xhtml"
    report.write_text("<html><body>nothing tagged</body></html>", encoding="utf-8")

    out = tmp_path / "ledgers"
    work = out / "doc"
    work.mkdir(parents=True)
    FactLedger(
        document_id="doc",
        content_hash=hash_file(report),
        builder_version="built-by-older-code",
    ).write(work / "ledger.json")
    (work / "document.pdf").write_bytes(b"%PDF-1.4 stub")

    # Rebuilding needs a browser, so the assertion is that it tries to.
    pytest.importorskip("playwright", reason="a real rebuild renders with Chromium")
    result = build_one(report, out)
    assert result.builder_version == label_plane_version()


def test_the_builder_version_moves_only_when_the_label_plane_changes() -> None:
    """Derived from the code, so nobody has to remember to bump it."""
    assert label_plane_version() == label_plane_version()
    assert len(label_plane_version()) == 64


def test_an_amended_filing_is_not_skipped(tmp_path: Path) -> None:
    """A stale ledger must be rebuilt, not returned because a file exists."""
    pytest.importorskip("playwright", reason="a real rebuild renders with Chromium")
    from disclosure_rag.labels.build import build_one

    filing = tmp_path / "filings" / "doc"
    filing.mkdir(parents=True)
    report = filing / "report.xhtml"
    report.write_text("<html><body>original</body></html>", encoding="utf-8")

    out = tmp_path / "ledgers"
    work = out / "doc"
    work.mkdir(parents=True)
    FactLedger(document_id="doc", content_hash="a-stale-hash").write(work / "ledger.json")
    (work / "document.pdf").write_bytes(b"%PDF-1.4 stub")

    result = build_one(report, out)
    assert result.content_hash == hash_file(report)
    assert result.content_hash != "a-stale-hash"


def test_a_forced_rebuild_ignores_an_up_to_date_ledger(tmp_path: Path) -> None:
    """An escape hatch for when the builder changed rather than the filing."""
    pytest.importorskip("playwright", reason="a real rebuild renders with Chromium")
    from disclosure_rag.labels.build import build_one

    filing = tmp_path / "filings" / "doc"
    filing.mkdir(parents=True)
    report = filing / "report.xhtml"
    report.write_text("<html><body>unchanged</body></html>", encoding="utf-8")

    out = tmp_path / "ledgers"
    work = out / "doc"
    work.mkdir(parents=True)
    stale = FactLedger(document_id="doc", content_hash=hash_file(report))
    stale.prose_pairs = []
    stale.write(work / "ledger.json")
    (work / "document.pdf").write_bytes(b"%PDF-1.4 stub")

    rebuilt = build_one(report, out, force=True)
    # A real build writes a real PDF over the stub.
    assert (work / "document.pdf").read_bytes() != b"%PDF-1.4 stub"
    assert rebuilt.content_hash == hash_file(report)
