"""Tests for the HTTP surface."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from disclosure_rag import __version__
from disclosure_rag.app import app


def test_health_reports_ok_and_version() -> None:
    with TestClient(app) as client:
        body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["version"] == __version__


def test_openapi_schema_is_generated() -> None:
    """Catches response-model mistakes that would otherwise fail at runtime."""
    with TestClient(app) as client:
        paths = client.get("/openapi.json").json()["paths"]
    assert {"/health", "/query", "/documents"} <= set(paths)


def test_the_service_starts_without_a_corpus() -> None:
    """A missing corpus must degrade, not crash: the image has no data baked in."""
    with TestClient(app) as client:
        assert client.get("/documents").json() == []


def test_querying_an_unknown_document_is_a_404() -> None:
    with TestClient(app) as client:
        response = client.post("/query", json={"question": "Bilanzsumme", "document_id": "absent"})
    assert response.status_code == 404


def test_an_empty_question_is_rejected_by_validation() -> None:
    with TestClient(app) as client:
        response = client.post("/query", json={"question": "", "document_id": "doc"})
    assert response.status_code == 422


def test_every_response_carries_a_request_id() -> None:
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.headers.get("x-request-id")


def test_a_missing_corpus_path_fails_the_start(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configured but unusable must not boot into a healthy, empty service.

    A service that reports healthy while abstaining on every question looks
    correct on a dashboard and is useless, which is the worse failure.
    """
    monkeypatch.setenv("DISCLOSURE_RAG_CORPUS", "/nonexistent/corpus")
    with pytest.raises(RuntimeError, match="does not exist"), TestClient(app):
        pass


def test_an_empty_corpus_directory_fails_the_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DISCLOSURE_RAG_CORPUS", str(tmp_path))
    with pytest.raises(RuntimeError, match="no usable documents"), TestClient(app):
        pass
