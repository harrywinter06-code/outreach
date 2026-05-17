import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock
from clawbot.skill_registry import SkillRegistry
from clawbot.skill_ctx import make_noop_ctx

BUILTIN_DIR = Path(__file__).parent.parent / "agents" / "skills" / "_builtin"


@pytest.fixture(scope="module")
def builtin_registry() -> SkillRegistry:
    reg = SkillRegistry(skills_dir=BUILTIN_DIR)
    reg.discover()
    return reg


EXPECTED_BUILTINS = {
    "http_fetch", "http_post", "llm_complete", "vector_search", "vector_write",
    "secret_get", "fs_read", "fs_write", "fs_list", "sql_query",
    "operator_message", "operator_request_approval", "time_now", "bus_publish",
    "worker_spawn", "worker_fire",
}


def test_all_expected_builtins_load(builtin_registry):
    loaded = set(builtin_registry.list_names())
    missing = EXPECTED_BUILTINS - loaded
    assert not missing, f"missing built-in skills: {missing}"


def test_http_fetch_returns_dict(builtin_registry):
    ctx = make_noop_ctx(caller_id="test", budget_usd=0.0)
    record = asyncio.run(builtin_registry.call(
        "http_fetch", {"url": "https://example.com"}, ctx,
    ))
    assert record.ok is True
    assert "text" in record.result
    assert "status" in record.result


def test_time_now_returns_iso(builtin_registry):
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    record = asyncio.run(builtin_registry.call("time_now", {}, ctx))
    assert record.ok is True
    assert "iso" in record.result


def test_worker_spawn_publishes_to_bus(builtin_registry):
    ctx = make_noop_ctx(caller_id="ceo", budget_usd=0)
    ctx.bus.publish = AsyncMock(return_value="msg-id")  # type: ignore[method-assign]
    record = asyncio.run(builtin_registry.call(
        "worker_spawn",
        {"role": "researcher", "soul_text": "you research things", "supervisor": "ceo"},
        ctx,
    ))
    assert record.ok is True
    ctx.bus.publish.assert_called_once()
    args = ctx.bus.publish.call_args.args
    assert args[0] == "agent.spawn_request"


def test_worker_fire_publishes_to_bus(builtin_registry):
    ctx = make_noop_ctx(caller_id="ceo", budget_usd=0)
    ctx.bus.publish = AsyncMock(return_value="msg-id")  # type: ignore[method-assign]
    record = asyncio.run(builtin_registry.call(
        "worker_fire", {"agent_id": "researcher-001", "reason": "redundant"}, ctx,
    ))
    assert record.ok is True
    topic, payload = ctx.bus.publish.call_args.args
    assert topic == "agent.fire_request"
    assert payload["agent_id"] == "researcher-001"
