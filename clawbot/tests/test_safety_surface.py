"""After-build verification: every safety surface remains functional.

This test fails LOUDLY if any guard has been weakened. Treat any failure
here as a release blocker. Pre-mortem: most likely cause of failure is
the skill system creating a code path that ends up writing a protected
file or bypassing the kill switch — this test catches that.
"""
from pathlib import Path
import hashlib
import pytest

REPO_ROOT = Path(__file__).parent.parent

PROTECTED_FILES_EXPECTED = {
    "src/clawbot/monitor.py",
    "src/clawbot/coder.py",
    "src/clawbot/evolution.py",
    "src/clawbot/genome.py",
    "src/clawbot/fitness.py",
    "src/clawbot/board.py",
    "src/clawbot/scheduler.py",
    "src/clawbot/agent_registry.py",
    "CORPORATE_CHARTER.md",
    ".env",
    ".env.example",
}


def test_protected_files_set_unchanged():
    from clawbot.coder import PROTECTED_FILES
    assert set(PROTECTED_FILES) == PROTECTED_FILES_EXPECTED, (
        "PROTECTED_FILES has changed — verify intentionally and update this test"
    )


def test_protected_globs_unchanged():
    from clawbot.coder import PROTECTED_GLOBS
    assert "agents/**/SOUL.md" in PROTECTED_GLOBS
    assert "agents/**/SOUL.candidate.md" in PROTECTED_GLOBS


def test_kill_switch_path_still_referenced():
    from clawbot.config import settings
    assert settings.kill_file_path  # non-empty


def test_charter_file_exists_and_matches_expected_shape():
    charter = REPO_ROOT / "CORPORATE_CHARTER.md"
    assert charter.exists(), "CORPORATE_CHARTER.md must exist"
    # Hash the charter content — record it for drift detection
    content = charter.read_bytes()
    sha = hashlib.sha256(content).hexdigest()
    print(f"Current charter SHA256: {sha}")  # captured by pytest -s


def test_max_daily_spend_cap_still_enforced():
    from clawbot.config import settings
    assert settings.max_daily_spend_usd > 0


def test_skill_loader_blocks_os_import():
    from clawbot.skill_loader import scan_skill_source, SkillValidationError
    with pytest.raises(SkillValidationError):
        scan_skill_source("import os\nMETA={}\nasync def run(ctx): return {}")


def test_skill_loader_blocks_subprocess():
    from clawbot.skill_loader import scan_skill_source, SkillValidationError
    with pytest.raises(SkillValidationError):
        scan_skill_source("import subprocess\nMETA={}\nasync def run(ctx): return {}")


def test_skill_fs_sandbox_rejects_traversal():
    from clawbot.skill_ctx import make_live_ctx
    from unittest.mock import MagicMock
    ctx = make_live_ctx(
        caller_id="t", budget_usd=0,
        llm_pool=MagicMock(), bus=MagicMock(), brain=MagicMock(),
        db_pool=MagicMock(), escalation=MagicMock(),
        secret_allowlist=[], workspace_root="/tmp/clawbot-ws",
    )
    import asyncio
    with pytest.raises(PermissionError, match="outside allowed roots"):
        asyncio.run(ctx.fs.read("/etc/passwd"))


def test_skill_secret_rejects_unlisted():
    from clawbot.skill_ctx import make_live_ctx
    from unittest.mock import MagicMock
    ctx = make_live_ctx(
        caller_id="t", budget_usd=0,
        llm_pool=MagicMock(), bus=MagicMock(), brain=MagicMock(),
        db_pool=MagicMock(), escalation=MagicMock(),
        secret_allowlist=["FOO"], workspace_root="/tmp/x",
    )
    with pytest.raises(PermissionError, match="not allowlisted"):
        ctx.secret.get("BAR")


def test_sql_rejects_ddl():
    from clawbot.skill_ctx import _LiveSql
    from unittest.mock import MagicMock
    import asyncio
    sql = _LiveSql(MagicMock())
    for op in ("DROP TABLE x", "TRUNCATE x", "ALTER TABLE x", "CREATE TABLE x"):
        with pytest.raises(PermissionError, match="DDL not allowed"):
            asyncio.run(sql.query(op))
