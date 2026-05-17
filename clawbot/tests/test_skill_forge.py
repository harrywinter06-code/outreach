import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import pytest
from clawbot.skill_forge import SkillForge
from clawbot.skill_registry import SkillRegistry


GOOD_DRAFT = '''META = {
    "name": "weather_check",
    "description": "Check weather for a city",
    "params": {"city": "str"},
    "returns": {"temp_c": "float"},
}

async def run(ctx, city: str) -> dict:
    response = await ctx.http.get(f"https://api.example/{city}")
    return {"temp_c": 20.0}
'''

BAD_DRAFT_FORBIDDEN_IMPORT = '''import os
META = {"name": "x", "description": "y", "params": {}, "returns": {}}
async def run(ctx): return {}
'''


@pytest.fixture
def temp_dirs(tmp_path: Path):
    skills = tmp_path / "skills"
    archive = tmp_path / "skills_archive"
    skills.mkdir()
    archive.mkdir()
    return skills, archive


def test_forge_promotes_passing_skill(temp_dirs):
    skills, archive = temp_dirs
    pool = MagicMock()
    pool.complete = AsyncMock(return_value=GOOD_DRAFT)
    bus = MagicMock()
    bus.publish = AsyncMock(return_value="id")
    registry = SkillRegistry(skills_dir=skills)
    registry.discover()
    brain = MagicMock()
    brain.recall = AsyncMock(return_value=[])
    brain.write = AsyncMock(return_value="vid")
    db_pool = MagicMock()
    escalation = MagicMock()

    forge = SkillForge(
        llm_pool=pool, bus=bus, registry=registry,
        skills_dir=skills, archive_dir=archive,
        brain=brain, db_pool=db_pool, escalation=escalation,
    )

    req = {
        "name": "weather_check",
        "description": "Check the weather",
        "params_schema": {"city": "str"},
        "returns_schema": {"temp_c": "float"},
        "example_call": {"city": "London"},
        "requested_by": "ceo",
    }
    asyncio.run(forge._handle_request(req))

    assert (skills / "weather_check.py").exists()


def test_forge_archives_skill_failing_ast_scan(temp_dirs):
    skills, archive = temp_dirs
    pool = MagicMock()
    pool.complete = AsyncMock(return_value=BAD_DRAFT_FORBIDDEN_IMPORT)
    forge = SkillForge(
        llm_pool=pool, bus=MagicMock(), registry=SkillRegistry(skills),
        skills_dir=skills, archive_dir=archive,
        brain=MagicMock(), db_pool=MagicMock(), escalation=MagicMock(),
    )

    asyncio.run(forge._handle_request({
        "name": "bad_skill", "description": "x", "params_schema": {},
        "returns_schema": {}, "example_call": {}, "requested_by": "ceo",
    }))

    assert not (skills / "bad_skill.py").exists()
    assert any(archive.iterdir())


def test_forge_rejects_skill_failing_shadow(temp_dirs):
    skills, archive = temp_dirs
    # Draft that raises an exception when called
    raising_draft = '''META = {"name": "boom", "description": "x", "params": {}, "returns": {}}
async def run(ctx) -> dict:
    raise ValueError("nope")
'''
    pool = MagicMock()
    pool.complete = AsyncMock(return_value=raising_draft)
    forge = SkillForge(
        llm_pool=pool, bus=MagicMock(), registry=SkillRegistry(skills),
        skills_dir=skills, archive_dir=archive,
        brain=MagicMock(), db_pool=MagicMock(), escalation=MagicMock(),
    )
    asyncio.run(forge._handle_request({
        "name": "boom", "description": "x", "params_schema": {},
        "returns_schema": {}, "example_call": {}, "requested_by": "ceo",
    }))
    assert not (skills / "boom.py").exists()
