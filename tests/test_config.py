"""Tests for settings loading.

These use a subclass with ``env_file=None`` rather than the settings object the
application uses. Reading the developer's local .env would make the assertions
depend on ambient state, so they would pass on a clean machine and then fail
confusingly the first time someone edited their own .env.

Subclassing rather than passing the undocumented ``_env_file`` argument keeps
this type-safe: pydantic-settings accepts that argument at runtime but does not
declare it, so mypy rejects it under strict mode.
"""

import pytest
from pydantic import ValidationError
from pydantic_settings import SettingsConfigDict

from disclosure_rag.config import Settings


class IsolatedSettings(Settings):
    """Settings that ignore any .env on disk, so tests read only the environment."""

    model_config = SettingsConfigDict(
        env_file=None,
        env_nested_delimiter="__",
        extra="ignore",
    )


def test_defaults_do_not_depend_on_a_local_dotenv() -> None:
    settings = IsolatedSettings()
    assert settings.environment == "local"
    assert settings.qdrant.collection == "disclosure_passages"


def test_environment_overrides_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "ci")
    assert IsolatedSettings().environment == "ci"


def test_nested_settings_use_the_double_underscore_delimiter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RETRIEVAL__TOP_K", "25")
    assert IsolatedSettings().retrieval.top_k == 25


def test_out_of_range_values_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bounds are declared on the settings models, so a bad value fails at load."""
    monkeypatch.setenv("ANSWER__ABSTAIN_BELOW", "1.5")
    with pytest.raises(ValidationError):
        IsolatedSettings()
