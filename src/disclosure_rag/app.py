"""FastAPI application.

``/query`` answers a question and returns the regions to outline. ``/page``
renders one of those regions onto the document page, which is what makes a
citation verifiable in one click rather than in principle. ``/`` serves a viewer
that puts the two together. ``/snapshot`` and ``/audit`` cover reproducing an
answer later, and ``/health`` and ``/metrics`` cover operating it.

The corpus is loaded once at startup and held in memory. At this size that is
the right call: the index is a few thousand chunks, so a network hop to a vector
database would cost more than the search.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field

from disclosure_rag import __version__
from disclosure_rag.answer.models import Answer
from disclosure_rag.answer.pipeline import AnswerPipeline
from disclosure_rag.audit import AuditLog, AuditRecord, ReplayResult, replay
from disclosure_rag.config import get_settings
from disclosure_rag.corpus import Corpus, load_corpus
from disclosure_rag.examples import working_examples
from disclosure_rag.metrics import Metrics
from disclosure_rag.render import render_page_with_regions
from disclosure_rag.versioning import Snapshot
from disclosure_rag.viewer import PAGE

logger = logging.getLogger("disclosure_rag")

CORPUS_ENV = "DISCLOSURE_RAG_CORPUS"
AUDIT_ENV = "DISCLOSURE_RAG_AUDIT_LOG"


class Health(BaseModel):
    status: Literal["ok"]
    version: str
    environment: str
    documents: int
    snapshot_id: str = Field(
        default="", description="Identifies the corpus and settings answers are produced against"
    )


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    document_id: str
    top_k: int = Field(default=10, ge=1, le=50)


class DocumentSummary(BaseModel):
    document_id: str
    pages: int
    tagged_facts: int
    chunks: int
    example_questions: list[str] = Field(
        default_factory=list,
        description="Questions this filing answers, verified at startup rather than assumed",
    )


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        format='{"level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    _configure_logging(settings.log_level)

    directory = os.environ.get(CORPUS_ENV)
    if not directory:
        # Deliberately empty: the image ships no data, so this is the normal
        # state for a container started without a mounted corpus.
        corpus = Corpus.empty()
        logger.warning(
            "no corpus configured. Set %s to a ledger directory built by "
            "disclosure_rag.labels.build",
            CORPUS_ENV,
        )
    else:
        # Configured but unusable is a misconfiguration, and it fails the start
        # rather than serving an empty index. A service that reports healthy
        # while answering nothing is worse than one that refuses to boot: the
        # first looks fine on a dashboard and abstains on every question.
        path = Path(directory)
        if not path.exists():
            raise RuntimeError(f"{CORPUS_ENV} is set to {directory!r}, which does not exist")
        corpus = load_corpus(path)
        if not corpus.ledgers:
            raise RuntimeError(
                f"{CORPUS_ENV} is set to {directory!r} but it holds no usable documents. "
                "Each document needs both ledger.json and document.pdf."
            )
        logger.info(
            "corpus loaded: %d documents, %d chunks", len(corpus.ledgers), len(corpus.chunks)
        )

    app.state.corpus = corpus
    app.state.pipeline = AnswerPipeline(
        corpus.ledgers,
        corpus.retriever,
        abstain_below=settings.answer.abstain_below,
        snapshot_id=corpus.snapshot.snapshot_id if corpus.snapshot else "",
    )
    # Answers are recorded when a log is configured. Off by default, because
    # writing an audit trail nobody asked for is its own kind of surprise.
    audit_path = os.environ.get(AUDIT_ENV)
    app.state.audit = AuditLog(Path(audit_path)) if audit_path else None
    app.state.metrics = Metrics()
    if audit_path:
        logger.info("recording answers to %s", audit_path)

    # Computed once, by asking. See disclosure_rag.examples for why an example
    # is verified rather than assumed.
    pipeline: AnswerPipeline = app.state.pipeline

    def asker(document_id: str) -> Callable[[str], Answer]:
        return lambda question: pipeline.answer(question, document_id)

    app.state.examples = {
        document_id: working_examples(ledger, asker(document_id))
        for document_id, ledger in corpus.ledgers.items()
    }
    yield


app = FastAPI(
    title="disclosure-rag",
    version=__version__,
    summary="Grounded question answering over EU financial filings.",
    lifespan=lifespan,
)


@app.middleware("http")
async def correlate(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Attach a request id and log the outcome and duration."""
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    start = time.perf_counter()
    response = await call_next(request)
    duration = (time.perf_counter() - start) * 1000
    response.headers["x-request-id"] = request_id
    logger.info(
        "%s %s -> %d in %.1fms (request_id=%s)",
        request.method,
        request.url.path,
        response.status_code,
        duration,
        request_id,
    )
    return response


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def viewer() -> str:
    """A page for asking a question and seeing the region the answer came from."""
    return PAGE


@app.get("/health", response_model=Health, tags=["ops"])
def health(request: Request) -> Health:
    settings = get_settings()
    return Health(
        status="ok",
        version=__version__,
        environment=settings.environment,
        documents=len(request.app.state.corpus.ledgers),
        snapshot_id=(
            request.app.state.corpus.snapshot.snapshot_id
            if request.app.state.corpus.snapshot
            else ""
        ),
    )


@app.get("/documents", response_model=list[DocumentSummary], tags=["corpus"])
def documents(request: Request) -> list[DocumentSummary]:
    corpus: Corpus = request.app.state.corpus
    return [
        DocumentSummary(
            document_id=document_id,
            pages=corpus.page_counts.get(document_id, 0),
            tagged_facts=len(ledger.facts),
            chunks=sum(1 for chunk in corpus.chunks if chunk.document_id == document_id),
            example_questions=request.app.state.examples.get(document_id, []),
        )
        for document_id, ledger in sorted(corpus.ledgers.items())
    ]


@app.post("/query", response_model=Answer, tags=["query"])
def query(request: Request, body: QueryRequest) -> Answer:
    corpus: Corpus = request.app.state.corpus
    if body.document_id not in corpus.ledgers:
        raise HTTPException(status_code=404, detail=f"unknown document {body.document_id!r}")
    pipeline: AnswerPipeline = request.app.state.pipeline
    answer = pipeline.answer(body.question, body.document_id, top_k=body.top_k)

    metrics: Metrics = request.app.state.metrics
    metrics.record_answer(answer.route.value, answer.status.value, sum(answer.timings_ms.values()))

    log: AuditLog | None = request.app.state.audit
    if log is not None and corpus.snapshot is not None:
        record = log.append(
            AuditRecord.create(body.question, body.document_id, answer, corpus.snapshot)
        )
        answer = answer.model_copy(update={"audit_id": record.record_id})
    return answer


@app.get("/metrics", response_class=PlainTextResponse, tags=["ops"])
def metrics(request: Request) -> str:
    """Prometheus exposition.

    The counter worth alerting on is the abstention rate: it rises long before
    anyone notices a wrong answer, and it is the earliest sign that a corpus has
    gone stale or a filing has changed shape.
    """
    corpus: Corpus = request.app.state.corpus
    collected: Metrics = request.app.state.metrics
    return collected.render(
        documents=len(corpus.ledgers),
        snapshot_id=corpus.snapshot.snapshot_id if corpus.snapshot else "",
    )


@app.get("/snapshot", response_model=Snapshot, tags=["audit"])
def snapshot(request: Request) -> Snapshot:
    """The corpus and settings currently in force.

    Every answer carries this id, so an answer can be tied back to exactly which
    version of which filings produced it.
    """
    current: Snapshot | None = request.app.state.corpus.snapshot
    if current is None:
        raise HTTPException(status_code=503, detail="no corpus loaded")
    return current


@app.get("/audit/{record_id}", response_model=AuditRecord, tags=["audit"])
def audit_record(request: Request, record_id: str) -> AuditRecord:
    log: AuditLog | None = request.app.state.audit
    if log is None:
        raise HTTPException(status_code=404, detail=f"no audit log configured, set {AUDIT_ENV}")
    record = log.get(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"unknown record {record_id!r}")
    return record


@app.post("/audit/{record_id}/replay", response_model=ReplayResult, tags=["audit"])
def audit_replay(request: Request, record_id: str) -> ReplayResult:
    """Re-run a recorded answer and report whether it still holds.

    Reproduced means the record is still evidence. Superseded means the corpus
    has moved on, which is a fact an auditor needs rather than a failure.
    Diverged means the corpus did not move and the answer did, which is a defect.
    """
    log: AuditLog | None = request.app.state.audit
    if log is None:
        raise HTTPException(status_code=404, detail=f"no audit log configured, set {AUDIT_ENV}")
    record = log.get(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"unknown record {record_id!r}")
    current: Snapshot | None = request.app.state.corpus.snapshot
    if current is None:
        raise HTTPException(status_code=503, detail="no corpus loaded")
    result = replay(record, request.app.state.pipeline, current)
    request.app.state.metrics.record_replay(result.outcome.value)
    return result


@app.get("/page/{document_id}/{page}.png", tags=["query"])
def page_image(
    request: Request,
    document_id: str,
    page: int,
    regions: str = Query(
        default="",
        description=(
            "Semicolon-separated regions to outline, each x0,y0,x1,y1 normalised to "
            "the page box. Exactly the spans a /query citation returns."
        ),
    ),
    dpi: int = Query(default=110, ge=72, le=300),
) -> Response:
    """Render a page with the cited regions outlined.

    This is the endpoint that turns a citation from a claim into something a
    reader can check.
    """
    corpus: Corpus = request.app.state.corpus
    pdf_path = corpus.pdf_paths.get(document_id)
    if pdf_path is None:
        raise HTTPException(status_code=404, detail=f"unknown document {document_id!r}")
    try:
        image = render_page_with_regions(pdf_path, page, regions, dpi=dpi)
    except IndexError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return Response(content=image, media_type="image/png")
