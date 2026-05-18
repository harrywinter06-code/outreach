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

def test_registry_records_unknown_skill_failure_to_stats_db(skills_dir: Path):
    """Z2.5b: early-return on unknown skill MUST still write to skill_calls.
    Without this, activity_score_72h shows 0 even when cycles are firing
    against hallucinated skill names."""
    from unittest.mock import AsyncMock, MagicMock
    reg = SkillRegistry(skills_dir=skills_dir)
    reg.discover()
    pool = MagicMock()
    conn = MagicMock()
    conn.execute = AsyncMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=None)
    pool.acquire = MagicMock(return_value=cm)
    reg.set_stats_db(pool)
    ctx = make_noop_ctx(caller_id="biz_runner", budget_usd=0.05, business_id="biz_x")
    record = asyncio.run(reg.call("not_a_real_skill", {}, ctx))
    assert record.ok is False
    conn.execute.assert_awaited_once()
    args = conn.execute.call_args.args
    assert "INSERT INTO skill_calls" in args[0]
    assert args[1] == "not_a_real_skill"
    assert args[7] == "biz_x", "business_id must be the last positional arg"


def test_registry_treats_inner_ok_false_as_failure(tmp_path: Path):
    """Z3.5: skills that silently degrade by returning {"ok": False, ...}
    were being recorded as ok=true (call didn't raise, dict had all META
    fields). Now the inner ok must be honored as authoritative — otherwise
    the cycle runner keeps hallucinating artifacts for posts that never
    happened (e.g. dev_to_publish with no DEVTO_API_KEY)."""
    d = tmp_path / "skills"
    d.mkdir()
    (d / "fake_publish.py").write_text("""
META = {"name": "fake_publish", "description": "p",
        "params": {}, "returns": {"ok": "bool", "url": "str"}}
async def run(ctx):
    return {"ok": False, "url": "", "error": "creds missing"}
""")
    reg = SkillRegistry(skills_dir=d)
    reg.discover()
    ctx = make_noop_ctx(caller_id="t", budget_usd=0.0)
    record = asyncio.run(reg.call("fake_publish", {}, ctx))
    assert record.ok is False
    assert "creds missing" in (record.error or "")


def test_registry_treats_inner_ok_true_as_success(tmp_path: Path):
    """Inverse: a skill explicitly returning ok=True must still be ok=true."""
    d = tmp_path / "skills"
    d.mkdir()
    (d / "fake_pub_ok.py").write_text("""
META = {"name": "fake_pub_ok", "description": "p",
        "params": {}, "returns": {"ok": "bool", "url": "str"}}
async def run(ctx):
    return {"ok": True, "url": "https://posted"}
""")
    reg = SkillRegistry(skills_dir=d)
    reg.discover()
    ctx = make_noop_ctx(caller_id="t", budget_usd=0.0)
    record = asyncio.run(reg.call("fake_pub_ok", {}, ctx))
    assert record.ok is True
    assert record.error is None


def test_registry_records_missing_param_failure_to_stats_db(skills_dir: Path):
    """Same fix for the missing-param early-return path."""
    from unittest.mock import AsyncMock, MagicMock
    reg = SkillRegistry(skills_dir=skills_dir)
    reg.discover()
    pool = MagicMock()
    conn = MagicMock()
    conn.execute = AsyncMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=None)
    pool.acquire = MagicMock(return_value=cm)
    reg.set_stats_db(pool)
    ctx = make_noop_ctx(caller_id="biz_runner", budget_usd=0.05, business_id="biz_y")
    record = asyncio.run(reg.call("echo", {}, ctx))  # echo requires `text`
    assert record.ok is False
    assert "missing required param" in record.error
    conn.execute.assert_awaited_once()
    args = conn.execute.call_args.args
    assert "INSERT INTO skill_calls" in args[0]
    assert args[7] == "biz_y"


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


NEW_SKILL = '''
META = {"name": "added_at_runtime", "description": "x", "params": {}, "returns": {}}
async def run(ctx) -> dict:
    return {"x": 1}
'''

def test_registry_hot_reloads_new_file(skills_dir):
    reg = SkillRegistry(skills_dir=skills_dir)
    reg.discover()
    assert "added_at_runtime" not in reg.list_names()

    async def add_and_wait():
        watcher_task = asyncio.create_task(reg.run_watcher())
        await asyncio.sleep(0.1)
        (skills_dir / "added_at_runtime.py").write_text(NEW_SKILL)
        # Wait up to 3s for watcher to pick it up
        for _ in range(30):
            await asyncio.sleep(0.1)
            if "added_at_runtime" in reg.list_names():
                break
        watcher_task.cancel()
        try:
            await watcher_task
        except asyncio.CancelledError:
            pass

    asyncio.run(add_and_wait())
    assert "added_at_runtime" in reg.list_names()


BAD_RETURNS_SKILL = '''
META = {"name": "wrong_returns", "description": "x", "params": {}, "returns": {"id": "str", "ok": "bool"}}
async def run(ctx) -> dict:
    return {"id": "x"}  # missing ok
'''


def test_registry_rejects_missing_return_fields(tmp_path: Path):
    d = tmp_path / "skills"
    d.mkdir()
    (d / "wrong_returns.py").write_text(BAD_RETURNS_SKILL)
    reg = SkillRegistry(skills_dir=d)
    reg.discover()
    rec = asyncio.run(reg.call("wrong_returns", {}, make_noop_ctx(caller_id="t", budget_usd=0)))
    assert rec.ok is False
    assert "missing return field: ok" in rec.error
