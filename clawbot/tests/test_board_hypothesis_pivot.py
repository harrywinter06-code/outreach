"""Board PIVOT outcome generates a new active_hypothesis."""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
import pytest


def _make_store_mock_with_pool(add_return: str = "hyp_abc", portfolio: list | None = None):
    """Build a store mock that supports the advisory-lock pool.acquire() pattern."""
    store_mock = MagicMock()
    store_mock.get_active_portfolio = AsyncMock(return_value=portfolio if portfolio is not None else [])
    store_mock.add_hypothesis = AsyncMock(return_value=add_return)
    store_mock.kill_hypothesis_by_id = AsyncMock()

    # Wire store._pool to support: async with pool.acquire() as conn: async with conn.transaction(): ...
    class _FakeConn:
        async def execute(self, *a, **k):
            pass

        def transaction(self):
            return _FakeTxn()

    class _FakeTxn:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *a):
            return False

    class _FakeAcquire:
        async def __aenter__(self):
            return _FakeConn()

        async def __aexit__(self, *a):
            return False

    pool_obj = MagicMock()
    pool_obj.acquire = MagicMock(return_value=_FakeAcquire())
    store_mock._pool = pool_obj
    return store_mock


@pytest.mark.asyncio
async def test_pivot_outcome_generates_new_hypothesis():
    from clawbot.board import generate_hypothesis_from_pivot

    pool = MagicMock()
    pool.complete = AsyncMock(return_value=json.dumps({
        "name": "H2",
        "description": "B2B research briefs sold to early-stage VCs at £500-2000 each",
        "kill_criteria": {"max_days_without_revenue": 21, "min_outreach_replies_by_day": [14, 2]},
    }))

    store_mock = _make_store_mock_with_pool(add_return="hyp_abc", portfolio=[])

    new_id = await generate_hypothesis_from_pivot(
        pool=pool,
        store=store_mock,
        previous_name="H1",
        previous_description="£9 IR35 PDF on Gumroad",
        pivot_rationale="0 sales after 14 days; market saturated with free LLM-generated PDFs",
    )
    assert new_id == "hyp_abc"
    store_mock.add_hypothesis.assert_called_once()
    kwargs = store_mock.add_hypothesis.call_args.kwargs
    assert kwargs["name"] == "H2"
    assert "B2B" in kwargs["description"]
    assert kwargs["kill_criteria"]["max_days_without_revenue"] == 21


@pytest.mark.asyncio
async def test_generate_hypothesis_handles_null_kill_criteria():
    """LLM returning null for kill_criteria must not crash the generator."""
    from clawbot.board import generate_hypothesis_for_portfolio

    pool = MagicMock()
    pool.complete = AsyncMock(return_value=json.dumps({
        "name": "H_test",
        "description": "test bet",
        "kill_criteria": None,  # null — must not crash
    }))
    store_mock = _make_store_mock_with_pool(add_return="hyp_null_test", portfolio=[])

    new_id = await generate_hypothesis_for_portfolio(
        pool=pool,
        store=store_mock,
        previous_name="H1",
        previous_description="x",
        pivot_rationale="test",
    )
    assert new_id == "hyp_null_test"
    # Verify kill_criteria was coerced to {}
    add_kwargs = store_mock.add_hypothesis.call_args.kwargs
    assert add_kwargs["kill_criteria"] == {}


@pytest.mark.asyncio
async def test_generate_hypothesis_evicts_lowest_weight_when_at_cap():
    """When portfolio is at cap, the lowest-weight hypothesis is killed."""
    from clawbot.board import generate_hypothesis_for_portfolio

    pool = MagicMock()
    pool.complete = AsyncMock(return_value=json.dumps({
        "name": "H_new",
        "description": "fresh bet",
        "kill_criteria": {"max_days_without_revenue": 14},
    }))
    portfolio = [
        {"hypothesis_id": "hyp_high", "weight": 0.7},
        {"hypothesis_id": "hyp_low", "weight": 0.1},
        {"hypothesis_id": "hyp_mid", "weight": 0.4},
    ]
    store_mock = _make_store_mock_with_pool(add_return="hyp_new_id", portfolio=portfolio)

    new_id = await generate_hypothesis_for_portfolio(
        pool=pool,
        store=store_mock,
        previous_name="H1",
        previous_description="x",
        pivot_rationale="stagnant",
        max_active=3,
    )
    assert new_id == "hyp_new_id"
    store_mock.kill_hypothesis_by_id.assert_called_once()
    kill_kwargs = store_mock.kill_hypothesis_by_id.call_args.kwargs
    assert kill_kwargs["hypothesis_id"] == "hyp_low"


@pytest.mark.asyncio
async def test_generate_hypothesis_raises_on_non_json_response():
    """Non-JSON LLM response must raise ValueError, not crash with AttributeError."""
    from clawbot.board import generate_hypothesis_for_portfolio

    pool = MagicMock()
    pool.complete = AsyncMock(return_value="Sorry, I cannot help with that.")
    store_mock = _make_store_mock_with_pool()

    with pytest.raises(ValueError, match="non-JSON"):
        await generate_hypothesis_for_portfolio(
            pool=pool,
            store=store_mock,
            previous_name="H1",
            previous_description="x",
            pivot_rationale="test",
        )


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
    hyp_store_mock.get_active_portfolio = AsyncMock(return_value=[{
        "name": "H2", "description": "B2B research briefs",
        "kill_criteria": {"max_days_without_revenue": 21},
        "status": "active",
        "weight": 0.33,
        "progress_score": 0.0,
    }])
    plan_store_mock = MagicMock()
    plan_store_mock.get_current_milestone = AsyncMock(return_value=None)
    with patch("clawbot.scheduler.HypothesisStore", return_value=hyp_store_mock), \
         patch("clawbot.scheduler.PlanStore", return_value=plan_store_mock):
        await s._run_executive_cycle()

    prompt_text = pool.complete.call_args.args[0][1]["content"]
    assert "H2" in prompt_text
    assert "B2B research briefs" in prompt_text
