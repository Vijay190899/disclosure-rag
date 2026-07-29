"""FastAPI application.

Only the health endpoint is implemented. The query and ingest endpoints are
specified in docs/TECHNICAL_DOCUMENTATION.md section 7 and land with milestones
M2 and M3 in docs/ROADMAP.md. This module exists now so that the documented
quickstart actually runs and so later tests have an app to mount.
"""

from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

from disclosure_rag import __version__
from disclosure_rag.config import get_settings


class Health(BaseModel):
    """Liveness response."""

    status: Literal["ok"]
    version: str
    environment: str


app = FastAPI(
    title="disclosure-rag",
    version=__version__,
    summary="Grounded question answering over EU financial filings.",
)


@app.get("/health", response_model=Health, tags=["ops"])
def health() -> Health:
    """Report liveness, build version and the active environment."""
    settings = get_settings()
    return Health(status="ok", version=__version__, environment=settings.environment)
