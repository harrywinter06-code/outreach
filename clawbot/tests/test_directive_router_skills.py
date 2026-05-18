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
async def test_router_strips_framing_fields_before_skill_call(tmp_path):
    """`dashboard_widget`, `priority`, `escalate`, `next_wakeup_s`, `business_id`
    must NOT leak into the skill's run() kwargs — they are framing fields
    consumed by the scheduler / router, not skill params."""
    router, _ = _make_router_with_skill(tmp_path)
    handler = router._get_handler("weather_check")
    assert handler is not None
    data = {
        "action": "weather_check",
        "city": "London",
        "dashboard_widget": {"id": "x", "type": "text", "title": "y", "content": "z"},
        "priority": "high",
        "escalate": False,
        "next_wakeup_s": 600,
        "business_id": "biz_xyz",
    }
    await handler(data, "chain-fr", "ceo")
    router._bus.publish_inbox.assert_called_once()
    target, payload = router._bus.publish_inbox.call_args.args
    assert payload["ok"] is True, f"skill should succeed; got: {payload!r}"


@pytest.mark.asyncio
async def test_router_threads_business_id_into_skill_ctx(tmp_path):
    """Z2.5: when the directive data includes business_id, it MUST reach
    make_live_ctx (so the SkillCtx.business_id is set and skill_calls
    rows attribute correctly)."""
    from unittest.mock import patch
    router, _ = _make_router_with_skill(tmp_path)
    handler = router._get_handler("weather_check")
    assert handler is not None
    captured = {}
    real_make_live_ctx = None
    from clawbot import skill_ctx as sc_mod
    real_make_live_ctx = sc_mod.make_live_ctx

    def _spy(**kwargs):
        captured.update(kwargs)
        return real_make_live_ctx(**kwargs)

    with patch("clawbot.skill_ctx.make_live_ctx", side_effect=_spy):
        await handler(
            {"action": "weather_check", "city": "London", "business_id": "biz_council_99"},
            "chain-bz", "biz_runner",
        )
    assert captured.get("business_id") == "biz_council_99", (
        f"router did not forward business_id to make_live_ctx; got: {captured!r}"
    )


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
