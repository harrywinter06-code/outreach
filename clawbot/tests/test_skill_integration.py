import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock


def test_main_wires_singleton_registry():
    from clawbot import skill_registry as mod
    skills_dir = Path(__file__).parent.parent / "agents" / "skills" / "_builtin"
    mod.init_skill_system(skills_dir=skills_dir)
    assert mod.REGISTRY is not None
    assert "http_fetch" in mod.REGISTRY.list_names()


from clawbot.skill_forge import SkillForge
from clawbot.skill_registry import SkillRegistry
from clawbot.skill_ctx import make_noop_ctx


GOOD_FORGE_OUTPUT = '''META = {
    "name": "double_it",
    "description": "Return 2*n",
    "params": {"n": "int"},
    "returns": {"result": "int"},
}

async def run(ctx, n: int) -> dict:
    return {"result": n * 2}
'''


@pytest.mark.asyncio
async def test_forge_then_directive_dispatches_via_router(tmp_path):
    # Setup: skills dir, registry, forge
    skills = tmp_path / "skills"
    archive = tmp_path / "archive"
    skills.mkdir()
    archive.mkdir()

    pool = MagicMock()
    pool.complete = AsyncMock(return_value=GOOD_FORGE_OUTPUT)
    bus = MagicMock()
    bus.publish = AsyncMock(return_value="id")
    bus.publish_inbox = AsyncMock()
    bus.ack = AsyncMock()
    brain = MagicMock()
    brain.write = AsyncMock(return_value="vid")

    registry = SkillRegistry(skills_dir=skills)
    registry.discover()
    from clawbot import skill_registry as mod
    mod.REGISTRY = registry

    forge = SkillForge(
        llm_pool=pool, bus=bus, registry=registry,
        skills_dir=skills, archive_dir=archive,
        brain=brain, db_pool=MagicMock(), escalation=MagicMock(),
    )

    # 1. Forge promotes a new skill from a request
    await forge._handle_request({
        "name": "double_it", "description": "double it",
        "params_schema": {"n": "int"}, "returns_schema": {"result": "int"},
        "example_call": {"n": 3}, "requested_by": "cfo",
    })
    assert "double_it" in registry.list_names()

    # 2. DirectiveRouter sees an action with that name → routes via fallback
    from clawbot.directive_router import DirectiveRouter
    causal = MagicMock(); causal.record_event = AsyncMock()
    router = DirectiveRouter(
        bus=bus, causal_store=causal, registry=MagicMock(),
        agent_factory=MagicMock(_pool=pool), task_store=MagicMock(),
        metrics_dir=tmp_path, brain=brain,
    )

    await router._handle_skill_call("double_it", {"n": 7}, "chain-9", "cfo")

    # 3. Result delivered to cfo's inbox
    bus.publish_inbox.assert_called_once()
    target, payload = bus.publish_inbox.call_args.args
    assert target == "cfo"
    assert payload["ok"] is True
    assert "14" in payload["message"]
