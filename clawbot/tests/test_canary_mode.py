import asyncio
from pathlib import Path
from clawbot.skill_registry import SkillRegistry


SKILL_THAT_FAILS = '''
META = {"name": "fails_canary", "description": "x",
        "params": {}, "returns": {"x": "int"}}
async def run(ctx) -> dict:
    raise RuntimeError("nope")
'''


def test_first_failure_demotes_skill(tmp_path: Path):
    skills = tmp_path / "skills"
    archive = tmp_path / "archive"
    skills.mkdir()
    archive.mkdir()
    (skills / "fails_canary.py").write_text(SKILL_THAT_FAILS)
    reg = SkillRegistry(skills_dir=skills, archive_dir=archive)
    reg.discover()
    assert "fails_canary" in reg.list_names()

    from clawbot.skill_ctx import make_noop_ctx
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    rec = asyncio.run(reg.call("fails_canary", {}, ctx))
    assert rec.ok is False

    # Auto-demote on first live failure (canary mode)
    reg.demote_on_canary_failure("fails_canary", reason=rec.error or "")

    assert "fails_canary" not in reg.list_names()
    assert not (skills / "fails_canary.py").exists()
    archived = list(archive.glob("*fails_canary*"))
    assert archived
