"""Per-pack load + representative-call test for the experiment skill pack."""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from clawbot.skill_ctx import make_noop_ctx
from clawbot.skill_registry import SkillRegistry

PACK_DIR = Path(__file__).parent.parent / "agents" / "skills" / "_builtin"
EXPECTED_EXPERIMENT_SKILLS = {
    "experiment_create", "experiment_record_observation",
    "experiment_compute_significance", "bandit_allocate_budget",
    "experiment_kill_underperformer", "experiment_summarize",
}


@pytest.fixture(scope="module")
def registry() -> SkillRegistry:
    reg = SkillRegistry(skills_dir=PACK_DIR)
    reg.discover()
    return reg


def test_experiment_pack_loads(registry: SkillRegistry) -> None:
    loaded = set(registry.list_names())
    missing = EXPECTED_EXPERIMENT_SKILLS - loaded
    assert not missing, f"experiment pack missing skills: {missing}"


def test_compute_significance_pure_math(registry: SkillRegistry) -> None:
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    record = asyncio.run(registry.call(
        "experiment_compute_significance",
        {"a_successes": 50, "a_trials": 100, "b_successes": 30, "b_trials": 100},
        ctx,
    ))
    assert record.ok is True, record.error
    assert record.result["winner"] == "A"
    assert 0.0 <= record.result["p_value"] <= 1.0
    assert record.result["lift"] > 0


def test_compute_significance_zero_trials(registry: SkillRegistry) -> None:
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    record = asyncio.run(registry.call(
        "experiment_compute_significance",
        {"a_successes": 0, "a_trials": 0, "b_successes": 5, "b_trials": 10},
        ctx,
    ))
    assert record.ok is True
    assert record.result["winner"] == "none"
    assert record.result["p_value"] == 1.0


def test_experiment_create_inserts(registry: SkillRegistry) -> None:
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    ctx.sql.query = AsyncMock(return_value=[])  # type: ignore[method-assign]
    record = asyncio.run(registry.call(
        "experiment_create",
        {"hypothesis": "blue button beats green", "metric": "click_rate"},
        ctx,
    ))
    assert record.ok is True, record.error
    assert record.result["experiment_id"].startswith("exp_")
    ctx.sql.query.assert_called_once()


def test_kill_underperformer_publishes_event(registry: SkillRegistry) -> None:
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    ctx.sql.query = AsyncMock(return_value=[  # type: ignore[method-assign]
        {"arm": "loser", "trials": 100, "successes": 1},
        {"arm": "winner", "trials": 100, "successes": 20},
        {"arm": "young", "trials": 5, "successes": 0},
    ])
    ctx.bus.publish = AsyncMock(return_value="msg-id")  # type: ignore[method-assign]
    record = asyncio.run(registry.call(
        "experiment_kill_underperformer",
        {"experiment_id": "exp_x", "threshold": 0.05, "min_trials": 30},
        ctx,
    ))
    assert record.ok is True, record.error
    assert record.result["killed_arms"] == ["loser"]
    assert "winner" in record.result["kept_arms"]
    assert "young" in record.result["kept_arms"]
    ctx.bus.publish.assert_called_once()
    topic, payload = ctx.bus.publish.call_args.args
    assert topic == "experiment.arm_killed"
    assert payload["arm"] == "loser"


def test_bandit_allocate_no_observations(registry: SkillRegistry) -> None:
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    record = asyncio.run(registry.call(
        "bandit_allocate_budget",
        {"experiment_id": "exp_x", "total_budget": 100.0},
        ctx,
    ))
    assert record.ok is True, record.error
    assert record.result["allocations"] == {}


def test_bandit_allocate_proportional_to_ucb1(registry: SkillRegistry) -> None:
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    ctx.sql.query = AsyncMock(return_value=[  # type: ignore[method-assign]
        {"arm": "A", "trials": 100, "successes": 30},
        {"arm": "B", "trials": 100, "successes": 60},
    ])
    record = asyncio.run(registry.call(
        "bandit_allocate_budget",
        {"experiment_id": "exp_x", "total_budget": 100.0},
        ctx,
    ))
    assert record.ok is True, record.error
    allocs = record.result["allocations"]
    assert set(allocs.keys()) == {"A", "B"}
    assert allocs["B"] > allocs["A"]
    assert abs(sum(allocs.values()) - 100.0) < 0.01
