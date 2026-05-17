import asyncio
import pytest
from pathlib import Path
from clawbot.skill_registry import SkillRegistry
from clawbot.skill_ctx import make_noop_ctx

SAMPLE_SKILL = '''
META = {
    "name": "echo",
    "description": "Return the input unchanged",
    "params": {"text": "str"},
    "returns": {"text": "str"},
}

async def run(ctx, text: str) -> dict:
    return {"text": text}
'''


@pytest.fixture
def skills_dir(tmp_path: Path) -> Path:
    d = tmp_path / "skills"
    d.mkdir()
    (d / "echo.py").write_text(SAMPLE_SKILL)
    return d


def test_registry_discovers_skill(skills_dir: Path):
    reg = SkillRegistry(skills_dir=skills_dir)
    reg.discover()
    assert "echo" in reg.list_names()

def test_registry_call_returns_skill_result(skills_dir: Path):
    reg = SkillRegistry(skills_dir=skills_dir)
    reg.discover()
    ctx = make_noop_ctx(caller_id="test", budget_usd=1.0)
    record = asyncio.run(reg.call("echo", {"text": "hello"}, ctx))
    assert record.ok is True
    assert record.result == {"text": "hello"}
    assert record.skill_name == "echo"

def test_registry_rejects_unknown_skill(skills_dir: Path):
    reg = SkillRegistry(skills_dir=skills_dir)
    reg.discover()
    ctx = make_noop_ctx(caller_id="test", budget_usd=1.0)
    record = asyncio.run(reg.call("nonexistent", {}, ctx))
    assert record.ok is False
    assert "unknown skill" in record.error.lower()

def test_registry_skips_files_failing_ast_scan(tmp_path: Path):
    d = tmp_path / "skills"
    d.mkdir()
    (d / "bad.py").write_text("import os\nMETA = {}\nasync def run(ctx): return {}")
    reg = SkillRegistry(skills_dir=d)
    reg.discover()
    assert "bad" not in reg.list_names()

def test_registry_enforces_param_schema(skills_dir: Path):
    reg = SkillRegistry(skills_dir=skills_dir)
    reg.discover()
    ctx = make_noop_ctx(caller_id="test", budget_usd=1.0)
    record = asyncio.run(reg.call("echo", {"wrong_param": "x"}, ctx))
    assert record.ok is False
    assert "missing required param: text" in record.error
