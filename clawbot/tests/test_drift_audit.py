import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from clawbot.drift_audit import (
    audit_agent, audit_all, write_drift_flags, AuditResult,
    _extract_immutable_section,
)


_GOOD_SOUL = """## IMMUTABLE

**Mandate:** Generate revenue. No spam.

## MUTABLE

### current_focus
Build IR35 PDF on Gumroad.
"""


_DRIFTED_SOUL = """## IMMUTABLE

**Mandate:** Generate revenue. No spam.

## MUTABLE

### current_focus
Mass-DM every UK contractor on LinkedIn until someone replies.
"""


def _write_soul(tmp_path: Path, agent_id: str, content: str) -> Path:
    soul = tmp_path / agent_id / "SOUL.md"
    soul.parent.mkdir(parents=True, exist_ok=True)
    soul.write_text(content, encoding="utf-8")
    return soul


def test_extract_immutable_section_returns_pre_mutable():
    assert "Mandate" in _extract_immutable_section(_GOOD_SOUL)
    assert "current_focus" not in _extract_immutable_section(_GOOD_SOUL)


def test_extract_immutable_section_returns_whole_text_when_no_marker():
    text = "no markers at all"
    assert _extract_immutable_section(text) == text


@pytest.mark.asyncio
async def test_audit_agent_returns_no_contradiction_for_aligned_soul(tmp_path):
    soul = _write_soul(tmp_path, "ceo", _GOOD_SOUL)
    pool = MagicMock()
    pool.complete = AsyncMock(return_value='{"contradicts": false, "reason": ""}')

    result = await audit_agent("ceo", soul, pool)
    assert result.contradicts is False
    assert result.agent_id == "ceo"


@pytest.mark.asyncio
async def test_audit_agent_returns_contradiction_for_drifted_soul(tmp_path):
    soul = _write_soul(tmp_path, "cmo", _DRIFTED_SOUL)
    pool = MagicMock()
    pool.complete = AsyncMock(
        return_value='{"contradicts": true, "reason": "Mass-DM violates the no-spam mandate."}'
    )

    result = await audit_agent("cmo", soul, pool)
    assert result.contradicts is True
    assert "spam" in result.reason.lower()


@pytest.mark.asyncio
async def test_audit_agent_handles_unparseable_response(tmp_path):
    soul = _write_soul(tmp_path, "ceo", _GOOD_SOUL)
    pool = MagicMock()
    pool.complete = AsyncMock(return_value="this is not JSON")

    result = await audit_agent("ceo", soul, pool)
    assert result.contradicts is False  # fail-safe: don't flag on parse error
    assert "unparseable" in result.reason.lower()


@pytest.mark.asyncio
async def test_audit_agent_missing_soul_returns_no_contradiction(tmp_path):
    pool = MagicMock()
    pool.complete = AsyncMock()
    result = await audit_agent("ghost", tmp_path / "ghost" / "SOUL.md", pool)
    assert result.contradicts is False
    pool.complete.assert_not_called()


@pytest.mark.asyncio
async def test_audit_agent_soul_without_mutable_returns_no_contradiction(tmp_path):
    """Constitutional agents (no MUTABLE section) cannot drift."""
    soul = _write_soul(tmp_path, "shareholder-activist", "## IMMUTABLE\nFixed mandate.\n")
    pool = MagicMock()
    pool.complete = AsyncMock()
    result = await audit_agent("shareholder-activist", soul, pool)
    assert result.contradicts is False
    pool.complete.assert_not_called()


@pytest.mark.asyncio
async def test_audit_agent_handles_llm_failure(tmp_path):
    soul = _write_soul(tmp_path, "ceo", _GOOD_SOUL)
    pool = MagicMock()
    pool.complete = AsyncMock(side_effect=RuntimeError("rate limit"))
    result = await audit_agent("ceo", soul, pool)
    assert result.contradicts is False  # don't flag on infra failure
    assert "unavailable" in result.reason.lower()


@pytest.mark.asyncio
async def test_audit_all_iterates_every_agent_dir(tmp_path):
    """Audit every agent; flag only the one with drifted content. Order-independent."""
    _write_soul(tmp_path, "ceo", _GOOD_SOUL)
    _write_soul(tmp_path, "cmo", _DRIFTED_SOUL)
    _write_soul(tmp_path, "cfo", _GOOD_SOUL)

    def _respond(messages, *args, **kwargs):
        user_msg = messages[1]["content"] if len(messages) > 1 else ""
        if "Mass-DM" in user_msg:
            return '{"contradicts": true, "reason": "spam mandate violated"}'
        return '{"contradicts": false, "reason": ""}'

    pool = MagicMock()
    pool.complete = AsyncMock(side_effect=_respond)

    results = await audit_all(tmp_path, pool)
    assert len(results) == 3
    flagged = [r for r in results if r.contradicts]
    assert len(flagged) == 1
    assert flagged[0].agent_id == "cmo"


@pytest.mark.asyncio
async def test_audit_strips_markdown_json_fences(tmp_path):
    """LLM commonly wraps JSON in ```json ... ``` fences; the audit must extract anyway."""
    soul = _write_soul(tmp_path, "ceo", _DRIFTED_SOUL)
    pool = MagicMock()
    pool.complete = AsyncMock(return_value=(
        '```json\n{"contradicts": true, "reason": "spam violation"}\n```'
    ))
    result = await audit_agent("ceo", soul, pool)
    assert result.contradicts is True
    assert "spam" in result.reason.lower()


@pytest.mark.asyncio
async def test_audit_extracts_json_when_preamble_present(tmp_path):
    """LLM may prepend 'Here is the response:' — extractor should still parse."""
    soul = _write_soul(tmp_path, "ceo", _DRIFTED_SOUL)
    pool = MagicMock()
    pool.complete = AsyncMock(return_value=(
        'Here is my analysis: {"contradicts": false, "reason": ""} — hope that helps!'
    ))
    result = await audit_agent("ceo", soul, pool)
    assert result.contradicts is False


def test_write_drift_flags_persists_flagged_agents(tmp_path):
    results = [
        AuditResult("ceo", contradicts=False, reason=""),
        AuditResult("cmo", contradicts=True, reason="violates no-spam"),
        AuditResult("cfo", contradicts=True, reason="violates spend limit"),
    ]
    write_drift_flags(tmp_path, results)
    data = json.loads((tmp_path / "drift_flags.json").read_text())
    assert data["audited_count"] == 3
    assert data["flagged_count"] == 2
    assert set(data["flagged_agents"]) == {"cmo", "cfo"}
    assert data["reasons"]["cmo"] == "violates no-spam"
