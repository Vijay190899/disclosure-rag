"""Tests for settings loading.

These deliberately construct ``Settings(_env_file=None)`` rather than calling
``get_settings()``. Reading the developer's local .env would make the
assertions depend on ambient state, so they would pass on a clean machine and
then fail confusingly the first time someone edits their own .env.
"""

import pytest
from pydantic import ValidationError

from disclosure_rag.config import Settings


def test_defaults_do_not_depend_on_a_local_dotenv() -> None:
    settings = Settings(_env_file=None)
    assert settings.environment == "local"
    assert settings.qdrant.collection == "disclosure_passages"


def test_environment_overrides_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "ci")
    assert Settings(_env_file=None).environment == "ci"


def test_nested_settings_use_the_double_underscore_delimiter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RETRIEVAL__TOP_K", "25")
    assert Settings(_env_file=None).retrieval.top_k == 25


def test_out_of_range_values_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bounds are declared on the settings models, so a bad value fails at load."""
    monkeypatch.setenv("ANSWER__ABSTAIN_BELOW", "1.5")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
