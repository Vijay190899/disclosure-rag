"""Tests for the FastAPI surface."""

from fastapi.testclient import TestClient

from disclosure_rag import __version__
from disclosure_rag.app import app

client = TestClient(app)


def test_health_reports_ok_and_version() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__


def test_openapi_schema_is_generated() -> None:
    """Catches response-model mistakes that would otherwise only fail at runtime."""
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert "/health" in response.json()["paths"]
