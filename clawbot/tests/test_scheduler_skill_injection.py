"""The executive cycle prompt must include the skill catalog block."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

import pytest


def _make_scheduler(tmp_path: Path):
    """Build a minimally-wired scheduler whose dependencies are mocks. Returns the
    scheduler + the captured pool so tests can inspect the prompt sent to the LLM.

    Adapter note: Scheduler.__init__ takes (pool, bus, monitor, registry, brain,
    homeostasis, agents_dir, metrics_dir, causal_store, task_store). The plan
    originally referenced factory/db_pool which don't exist — adjusted to the real
    signature."""
    from clawbot.scheduler import Scheduler

    bus = MagicMock()
    bus.publish = AsyncMock(return_value="msg-id")
    bus.read_and_ack = AsyncMock(return_value=[])
    pool = MagicMock()
    pool.complete = AsyncMock(return_value='{"action":"wait","directive":"test"}')
    monitor = MagicMock()
    brain = MagicMock()
    brain.search = AsyncMock(return_value=[])

    agents_dir = tmp_path / "agents"
    (agents_dir / "ceo").mkdir(parents=True)
    (agents_dir / "ceo" / "SOUL.md").write_text("# CEO\nMinimal SOUL for testing.\n")
    (agents_dir / "cto").mkdir(parents=True)
    (agents_dir / "cto" / "SOUL.md").write_text("# CTO\nMinimal SOUL.\n")

    metrics_dir = tmp_path / "metrics"
    metrics_dir.mkdir()
    # _load_metrics reads company_metrics.json, not company.json
    (metrics_dir / "company_metrics.json").write_text(
        '{"revenue_7d_gbp": 0, "worker_count": 0}'
    )

    s = Scheduler(
        pool=pool,
        bus=bus,
        monitor=monitor,
        brain=brain,
        agents_dir=agents_dir,
        metrics_dir=metrics_dir,
    )
    return s, pool


@pytest.mark.asyncio
async def test_executive_cycle_prompt_contains_skill_catalog(tmp_path):
    from clawbot.skill_catalog_renderer import SkillCatalogEntry
    s, pool = _make_scheduler(tmp_path)

    fake_entries = [SkillCatalogEntry(
        name="fs_write", description="Write to workspace",
        params={"path": "str", "content": "str"}, roles=[],
    )]
    with patch("clawbot.scheduler._load_skill_catalog", return_value=fake_entries):
        await s._run_executive_cycle()

    pool.complete.assert_called_once()
    prompt_text = pool.complete.call_args.args[0][1]["content"]
    assert "fs_write" in prompt_text
    # Compact mode: descriptions are omitted; only skill names appear in cycle prompts.
    assert "Write to workspace" not in prompt_text
    assert '"action": "<name>"' in prompt_text


@pytest.mark.asyncio
async def test_lieutenant_cycle_prompt_contains_skill_catalog(tmp_path):
    from clawbot.skill_catalog_renderer import SkillCatalogEntry
    s, pool = _make_scheduler(tmp_path)

    fake_entries = [SkillCatalogEntry(
        name="stripe_issue_card", description="Issue Stripe card",
        params={"cardholder_id": "str", "daily_limit_usd": "int", "agent_id": "str"},
        roles=["cfo"],
    )]
    (tmp_path / "agents" / "cfo").mkdir()
    (tmp_path / "agents" / "cfo" / "SOUL.md").write_text("# CFO\n")
    with patch("clawbot.scheduler._load_skill_catalog", return_value=fake_entries):
        await s._run_lieutenant_cycle("cfo")

    pool.complete.assert_called_once()
    prompt_text = pool.complete.call_args.args[0][1]["content"]
    assert "stripe_issue_card" in prompt_text
    # Compact mode: params are omitted; only skill names appear in cycle prompts.
    assert "cardholder_id" not in prompt_text


@pytest.mark.asyncio
async def test_cfo_does_not_see_cmo_only_skills(tmp_path):
    from clawbot.skill_catalog_renderer import SkillCatalogEntry
    s, pool = _make_scheduler(tmp_path)

    fake_entries = [SkillCatalogEntry(
        name="x_post", description="Post to X", params={"text": "str"}, roles=["cmo"],
    )]
    (tmp_path / "agents" / "cfo").mkdir()
    (tmp_path / "agents" / "cfo" / "SOUL.md").write_text("# CFO\n")
    with patch("clawbot.scheduler._load_skill_catalog", return_value=fake_entries):
        await s._run_lieutenant_cycle("cfo")
    prompt_text = pool.complete.call_args.args[0][1]["content"]
    assert "x_post" not in prompt_text
