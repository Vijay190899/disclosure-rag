"""Smoke tests so CI has something green to stand on from day one."""

from finrag import __version__
from finrag.config import get_settings


def test_version_is_set():
    assert __version__


def test_settings_have_defaults():
    settings = get_settings()
    assert settings.qdrant_collection == "finrag_documents"
    assert settings.environment == "local"
