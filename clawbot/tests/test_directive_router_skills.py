import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock


SAMPLE_SKILL = '''
META = {
    "name": "weather_check",
    "description": "Pretend to check weather",
    "params": {"city": "str"},
    "returns": {"temp_c": "float"},
}

async def run(ctx, city: str) -> dict:
    return {"temp_c": 18.5}
'''


def _make_router_with_skill(tmp_path: Path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir(exist_ok=True)
    (skills_dir / "weather_check.py").write_text(SAMPLE_SKILL)

    from clawbot.skill_registry import SkillRegistry
    from clawbot import skill_registry as mod
    reg = SkillRegistry(skills_dir=skills_dir)
    reg.discover()
    mod.REGISTRY = reg

    from clawbot.directive_router import DirectiveRouter
    bus = MagicMock()
    bus.publish = AsyncMock()
    bus.publish_inbox = AsyncMock()
    bus.ack = AsyncMock()
    causal = MagicMock()
    causal.record_event = AsyncMock()
    registry = MagicMock()
    factory = MagicMock()
    factory._pool = MagicMock()
    task_store = MagicMock()
    brain = MagicMock()
    brain.write = AsyncMock(return_value="vid")

    router = DirectiveRouter(
        bus=bus, causal_store=causal, registry=registry,
        agent_factory=factory, task_store=task_store,
        metrics_dir=tmp_path, brain=brain,
    )
    return router, reg


@pytest.mark.asyncio
async def test_router_dispatches_registered_skill(tmp_path):
    router, _ = _make_router_with_skill(tmp_path)
    # Skill is not in hardcoded handlers, so it must come through the fallback
    handler = router._get_handler("weather_check")
    assert handler is not None, "skill fallback did not resolve weather_check"


@pytest.mark.asyncio
async def test_router_publishes_skill_result_to_inbox(tmp_path):
    router, _ = _make_router_with_skill(tmp_path)
    await router._handle_skill_call(
        "weather_check", {"city": "London"}, "chain-1", "cmo",
    )
    router._bus.publish_inbox.assert_called_once()
    target, payload = router._bus.publish_inbox.call_args.args
    assert target == "cmo"
    assert payload["from"] == "skill:weather_check"
    assert "18.5" in payload["message"]


@pytest.mark.asyncio
async def test_router_publishes_skill_error_to_inbox(tmp_path):
    router, _ = _make_router_with_skill(tmp_path)
    # Missing required param
    await router._handle_skill_call(
        "weather_check", {}, "chain-2", "ceo",
    )
    router._bus.publish_inbox.assert_called_once()
    target, payload = router._bus.publish_inbox.call_args.args
    assert payload["ok"] is False
    assert "missing required param" in payload["message"]


@pytest.mark.asyncio
async def test_hardcoded_handler_wins_over_skill(tmp_path):
    """A hardcoded action name must NOT be shadowed by a same-named skill."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "hire.py").write_text(SAMPLE_SKILL.replace("weather_check", "hire"))
    from clawbot.skill_registry import SkillRegistry
    from clawbot import skill_registry as mod
    mod.REGISTRY = SkillRegistry(skills_dir=skills_dir)
    mod.REGISTRY.discover()

    router, _ = _make_router_with_skill(tmp_path)
    handler = router._get_handler("hire")
    # Hardcoded _handle_hire should still win
    assert handler == router._handle_hire
