"""Infrastructure health skills — db_health, redis_health, status_report."""
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


def test_infra_pack_loads():
    reg = _registry()
    names = set(reg.list_names())
    assert {"infra_db_health", "infra_redis_health", "infra_status_report"} <= names


def test_db_health_returns_ok_when_query_succeeds():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="cto", budget_usd=0)
    ctx.sql.query = AsyncMock(return_value=[{"one": 1}])
    record = asyncio.run(reg.call("infra_db_health", {}, ctx))
    assert record.ok is True
    assert record.result["ok"] is True
    assert "latency_ms" in record.result


def test_db_health_returns_not_ok_on_query_error():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="cto", budget_usd=0)
    async def boom(*a, **k):
        raise RuntimeError("connection refused")
    ctx.sql.query = boom
    record = asyncio.run(reg.call("infra_db_health", {}, ctx))
    assert record.ok is True  # skill itself succeeded
    assert record.result["ok"] is False
    assert "connection refused" in record.result.get("error", "")


def test_redis_health_uses_bus_publish():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="cto", budget_usd=0)
    ctx.bus.publish = AsyncMock(return_value="msg-id-123")
    record = asyncio.run(reg.call("infra_redis_health", {}, ctx))
    assert record.ok is True
    assert record.result["ok"] is True
    ctx.bus.publish.assert_called_once()


def test_status_report_composes_both():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="cto", budget_usd=0)
    ctx.sql.query = AsyncMock(return_value=[{"one": 1}])
    ctx.bus.publish = AsyncMock(return_value="msg-id")
    record = asyncio.run(reg.call("infra_status_report", {}, ctx))
    assert record.ok is True
    assert record.result["db_ok"] is True
    assert record.result["redis_ok"] is True
    assert "skill_calls_last_hour" in record.result
