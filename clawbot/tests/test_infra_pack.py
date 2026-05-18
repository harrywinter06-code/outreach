"""Builtin infra pack — health checks and status reporting."""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

from clawbot.skill_registry import SkillRegistry
from clawbot.skill_ctx import make_noop_ctx

BUILTIN_DIR = Path(__file__).parent.parent / "agents" / "skills" / "_builtin"


def _registry() -> SkillRegistry:
    reg = SkillRegistry(skills_dir=BUILTIN_DIR)
    reg.discover()
    return reg


INFRA_SKILLS = {
    "infra_db_health",
    "infra_status_report",
}


def test_infra_pack_loads():
    """Infra skills are discoverable."""
    reg = _registry()
    loaded = set(reg.list_names())
    missing = INFRA_SKILLS - loaded
    assert not missing, f"missing infra skills: {missing}"


def test_db_health_returns_not_ok_against_raw_noop_ctx():
    """Vanilla noop ctx has _NoopSql returning [], so db_health should report unhealthy.

    This is a regression test for audit finding: the skill should reject empty rows
    from a noop context and report ok=False, not silently accept [] as success.
    """
    reg = _registry()
    ctx = make_noop_ctx(caller_id="cto", budget_usd=0)
    # NO override of ctx.sql.query — use the raw noop behaviour which returns []
    record = asyncio.run(reg.call("infra_db_health", {}, ctx))
    assert record.ok is True  # the skill itself runs fine and returns a result dict
    assert record.result["ok"] is False  # but DB is "down" (empty rows)
    assert "returned no rows" in record.result["error"]


def test_status_report_ok_against_mocked_db():
    """Status report returns ok=True when DB check succeeds."""
    reg = _registry()
    ctx = make_noop_ctx(caller_id="cto", budget_usd=0)
    # Mock successful DB queries
    async def mock_query(sql):
        if "SELECT 1" in sql:
            return [{"one": 1}]
        if "skill_calls" in sql:
            return [{"n": 42}]
        return []
    ctx.sql.query = AsyncMock(side_effect=mock_query)  # type: ignore[method-assign]
    record = asyncio.run(reg.call("infra_status_report", {}, ctx))
    assert record.ok is True
    assert record.result["ok"] is True
    assert record.result["db_health"]["ok"] is True
    assert record.result["skill_calls_last_hour"] == 42


def test_status_report_not_ok_against_broken_db():
    """Status report returns ok=False when DB check fails."""
    reg = _registry()
    ctx = make_noop_ctx(caller_id="cto", budget_usd=0)
    # Mock failed DB query
    async def mock_query(sql):
        raise RuntimeError("connection refused")
    ctx.sql.query = AsyncMock(side_effect=mock_query)  # type: ignore[method-assign]
    record = asyncio.run(reg.call("infra_status_report", {}, ctx))
    assert record.ok is True
    assert record.result["ok"] is False
    assert record.result["db_health"]["ok"] is False
    assert "connection refused" in record.result["db_health"]["error"]
