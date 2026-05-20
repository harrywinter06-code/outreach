"""require_env() must raise loudly when a required var is missing or blank."""

from __future__ import annotations

import pytest

from config import require_env


def test_require_env_returns_value_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REQUIRE_ENV_TEST_PRESENT", "actual-value")
    assert require_env("REQUIRE_ENV_TEST_PRESENT") == "actual-value"


def test_require_env_strips_surrounding_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REQUIRE_ENV_TEST_WHITESPACE", "  padded  ")
    assert require_env("REQUIRE_ENV_TEST_WHITESPACE") == "padded"


def test_require_env_raises_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REQUIRE_ENV_TEST_MISSING", raising=False)
    with pytest.raises(EnvironmentError) as exc_info:
        require_env("REQUIRE_ENV_TEST_MISSING")
    assert "REQUIRE_ENV_TEST_MISSING" in str(exc_info.value)


def test_require_env_raises_when_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REQUIRE_ENV_TEST_EMPTY", "")
    with pytest.raises(EnvironmentError):
        require_env("REQUIRE_ENV_TEST_EMPTY")


def test_require_env_raises_when_only_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REQUIRE_ENV_TEST_WS_ONLY", "   ")
    with pytest.raises(EnvironmentError):
        require_env("REQUIRE_ENV_TEST_WS_ONLY")


def test_require_env_message_includes_purpose(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REQUIRE_ENV_TEST_PURPOSE", raising=False)
    with pytest.raises(EnvironmentError) as exc_info:
        require_env("REQUIRE_ENV_TEST_PURPOSE", purpose="signing emails")
    assert "signing emails" in str(exc_info.value)
