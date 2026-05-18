"""Board PIVOT outcome generates a new active_hypothesis."""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
import pytest


@pytest.mark.asyncio
async def test_pivot_outcome_generates_new_hypothesis():
    from clawbot.board import generate_hypothesis_from_pivot

    pool = MagicMock()
    pool.complete = AsyncMock(return_value=json.dumps({
        "name": "H2",
        "description": "B2B research briefs sold to early-stage VCs at £500-2000 each",
        "kill_criteria": {"max_days_without_revenue": 21, "min_outreach_replies_by_day": [14, 2]},
    }))

    store_mock = MagicMock()
    store_mock.set_active = AsyncMock(return_value="hyp_abc")

    new_id = await generate_hypothesis_from_pivot(
        pool=pool,
        store=store_mock,
        previous_name="H1",
        previous_description="£9 IR35 PDF on Gumroad",
        pivot_rationale="0 sales after 14 days; market saturated with free LLM-generated PDFs",
    )
    assert new_id == "hyp_abc"
    store_mock.set_active.assert_called_once()
    kwargs = store_mock.set_active.call_args.kwargs
    assert kwargs["name"] == "H2"
    assert "B2B" in kwargs["description"]
    assert kwargs["kill_criteria"]["max_days_without_revenue"] == 21


@pytest.mark.asyncio
async def test_ceo_cycle_prompt_includes_active_hypothesis(tmp_path):
    """CEO sees the active hypothesis as a top-level strategic constraint."""
    from clawbot.scheduler import Scheduler
    bus = MagicMock(); bus.publish = AsyncMock(); bus.read_and_ack = AsyncMock(return_value=[])
    pool = MagicMock(); pool.complete = AsyncMock(return_value='{"action":"wait"}')
    brain = MagicMock(); brain.search = AsyncMock(return_value=[])
    monitor = MagicMock(); monitor.get_budget_fraction = AsyncMock(return_value=0.0)

    agents_dir = tmp_path / "agents"
    (agents_dir / "ceo").mkdir(parents=True)
    (agents_dir / "ceo" / "SOUL.md").write_text("# CEO\n")
    metrics_dir = tmp_path / "metrics"
    metrics_dir.mkdir()
    (metrics_dir / "company_metrics.json").write_text('{"revenue_7d_gbp": 0}')
    s = Scheduler(
        pool=pool, bus=bus, brain=brain, monitor=monitor,
        agents_dir=agents_dir, metrics_dir=metrics_dir, db_pool=object(),
    )

    hyp_store_mock = MagicMock()
    hyp_store_mock.get_active = AsyncMock(return_value={
        "name": "H2", "description": "B2B research briefs",
        "kill_criteria": {"max_days_without_revenue": 21},
        "status": "active",
    })
    plan_store_mock = MagicMock()
    plan_store_mock.get_current_milestone = AsyncMock(return_value=None)
    with patch("clawbot.scheduler.HypothesisStore", return_value=hyp_store_mock), \
         patch("clawbot.scheduler.PlanStore", return_value=plan_store_mock):
        await s._run_executive_cycle()

    prompt_text = pool.complete.call_args.args[0][1]["content"]
    assert "H2" in prompt_text
    assert "B2B research briefs" in prompt_text
