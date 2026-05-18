"""End-to-end: cycle reads plan → injects to prompt → router updates on response."""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

import pytest


def _scheduler_with_plan_mock(tmp_path: Path, agent_id: str):
    """Build a minimally-wired scheduler. Returns the scheduler + pool mock so
    tests can inspect the prompt sent to the LLM.

    Adapter note: Scheduler.__init__ takes (pool, bus, monitor, registry, brain,
    homeostasis, agents_dir, metrics_dir, causal_store, task_store). The plan spec
    referenced factory/db_pool which don't exist — adjusted to the real signature."""
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
    (agents_dir / agent_id).mkdir(parents=True)
    (agents_dir / agent_id / "SOUL.md").write_text(f"# {agent_id}\n")
    metrics_dir = tmp_path / "metrics"
    metrics_dir.mkdir()
    (metrics_dir / "company_metrics.json").write_text('{"revenue_7d_gbp": 0}')

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
async def test_cycle_prompt_includes_current_milestone(tmp_path):
    s, pool = _scheduler_with_plan_mock(tmp_path, "cmo")

    fake_milestone = MagicMock()
    fake_milestone.milestone_idx = 0
    fake_milestone.hypothesis = "Substack pilot — 3 posts in 7 days"
    fake_milestone.success_criteria = json.dumps(["3 posts published", "subs > 0"])
    fake_milestone.evidence = json.dumps([{"kind": "skill_call", "skill": "fs_write"}])

    plan_store_mock = MagicMock()
    plan_store_mock.get_current_milestone = AsyncMock(return_value=fake_milestone)

    s._db_pool = object()  # satisfy the hasattr guard so PlanStore() is called
    with patch("clawbot.scheduler.PlanStore", return_value=plan_store_mock):
        await s._run_lieutenant_cycle("cmo")

    prompt_text = pool.complete.call_args.args[0][1]["content"]
    assert "Substack pilot" in prompt_text
    assert "3 posts published" in prompt_text
    assert "skill_call" in prompt_text


@pytest.mark.asyncio
async def test_cycle_prompt_signals_no_plan_when_none(tmp_path):
    s, pool = _scheduler_with_plan_mock(tmp_path, "cmo")
    plan_store_mock = MagicMock()
    plan_store_mock.get_current_milestone = AsyncMock(return_value=None)
    s._db_pool = object()  # satisfy the hasattr guard so PlanStore() is called
    with patch("clawbot.scheduler.PlanStore", return_value=plan_store_mock):
        await s._run_lieutenant_cycle("cmo")
    prompt_text = pool.complete.call_args.args[0][1]["content"]
    assert "no active plan" in prompt_text.lower()


@pytest.mark.asyncio
async def test_plan_init_action_creates_plan_in_store(tmp_path):
    from clawbot.directive_router import DirectiveRouter

    bus = MagicMock()
    bus.publish = AsyncMock()
    causal_store = MagicMock()
    causal_store.record_event = AsyncMock()
    registry = MagicMock()
    registry.get = AsyncMock(return_value=None)
    factory = MagicMock()
    task_store = MagicMock()

    router = DirectiveRouter(
        bus=bus,
        causal_store=causal_store,
        registry=registry,
        agent_factory=factory,
        task_store=task_store,
        metrics_dir=tmp_path / "metrics",
    )

    plan_store_mock = MagicMock()
    plan_store_mock.create_plan = AsyncMock(return_value="plan_abc")
    router._plan_store = plan_store_mock

    await router._handle_plan_init(
        data={
            "action": "plan_init",
            "hypothesis": "Substack pilot",
            "milestones": [
                {"hypothesis": "3 posts in 7 days", "success_criteria": ["3 posts"]},
            ],
        },
        chain_id="c", from_agent="cmo",
    )
    plan_store_mock.create_plan.assert_called_once()
    kwargs = plan_store_mock.create_plan.call_args.kwargs
    assert kwargs["agent_id"] == "cmo"
    assert kwargs["hypothesis"] == "Substack pilot"


def test_scheduler_constructor_accepts_db_pool():
    """Regression: db_pool must be a real constructor kwarg, not a setattr-after-init.
    The previous code referenced self._db_pool without setting it, so plan
    injection silently disabled in production. This test fails closed."""
    from clawbot.scheduler import Scheduler
    import inspect
    sig = inspect.signature(Scheduler.__init__)
    assert "db_pool" in sig.parameters, (
        f"Scheduler.__init__ must accept db_pool kwarg; got {list(sig.parameters)}"
    )


def test_directive_router_constructor_accepts_db_pool():
    from clawbot.directive_router import DirectiveRouter
    import inspect
    sig = inspect.signature(DirectiveRouter.__init__)
    assert "db_pool" in sig.parameters, (
        f"DirectiveRouter.__init__ must accept db_pool kwarg; got {list(sig.parameters)}"
    )


@pytest.mark.asyncio
async def test_plan_handler_raises_clearly_when_no_db_pool():
    from clawbot.directive_router import DirectiveRouter
    from unittest.mock import AsyncMock, MagicMock
    bus = MagicMock(); bus.publish = AsyncMock()
    # Construct router WITHOUT db_pool — handler should raise RuntimeError, not
    # AttributeError. Use bare-minimum constructor signature — adapt if needed.
    sig_params = {
        "bus": bus,
        "agent_factory": MagicMock(),
        "brain": MagicMock(),
        "metrics_dir": Path("/tmp/test_metrics_no_pool"),
    }
    # Auto-add other required args by introspecting __init__
    import inspect
    real_sig = inspect.signature(DirectiveRouter.__init__)
    for pname, param in real_sig.parameters.items():
        if pname == "self" or pname in sig_params or pname == "db_pool":
            continue
        if param.default is inspect.Parameter.empty:
            sig_params[pname] = MagicMock()
    router = DirectiveRouter(**sig_params, db_pool=None)
    with pytest.raises(RuntimeError, match="db_pool"):
        await router._handle_plan_advance(data={}, chain_id="c", from_agent="cmo")
