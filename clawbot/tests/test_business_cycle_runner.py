"""Z2.5b — BusinessCycleRunner unit tests with mocked LLM + store."""
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

UTC = timezone.utc


def _make_business(*, business_id="b1", name="bt", revenue=0.0,
                   spawned_days_ago=0.5, metadata=None):
    from clawbot.business_store import Business
    return Business(
        business_id=business_id, name=name, niche="x",
        genome={"niche_question": "what?", "price_gbp": 3.0,
                "channels": ["dev_to"], "copy_voice": "p",
                "fulfilment_template": "v1", "target_audience": "uk"},
        status="active", parent_id=None, template_id=None,
        budget_remaining_gbp=1.0, revenue_total_gbp=float(revenue),
        fitness_score=0.0,
        spawned_at=datetime.now(UTC) - timedelta(days=spawned_days_ago),
        last_cycle_at=None, killed_at=None, kill_reason=None,
        metadata=metadata or {},
    )


def test_parse_action_json_handles_plain_json():
    from clawbot.business_cycle_runner import _parse_action_json
    assert _parse_action_json('{"action": "x"}') == {"action": "x"}


def test_parse_action_json_strips_code_fence():
    from clawbot.business_cycle_runner import _parse_action_json
    out = _parse_action_json('```json\n{"action": "dev_to_publish", "title": "t"}\n```')
    assert out == {"action": "dev_to_publish", "title": "t"}


def test_parse_action_json_extracts_first_object_from_prose():
    from clawbot.business_cycle_runner import _parse_action_json
    raw = 'Sure, here is the action:\n{"action": "wait"} hope that helps.'
    assert _parse_action_json(raw) == {"action": "wait"}


def test_parse_action_json_returns_none_for_garbage():
    from clawbot.business_cycle_runner import _parse_action_json
    assert _parse_action_json("hello world no json here") is None
    assert _parse_action_json("") is None


def test_action_produces_artifact_recognises_publish_actions():
    from clawbot.business_cycle_runner import action_produces_artifact
    assert action_produces_artifact("dev_to_publish") is True
    assert action_produces_artifact("bluesky_post") is True
    assert action_produces_artifact("stripe_create_payment_link") is True
    assert action_produces_artifact("wait") is False
    assert action_produces_artifact("llm_complete") is False
    assert action_produces_artifact("") is False


@pytest.mark.asyncio
async def test_cycle_with_artifact_action_returns_true_and_resets_stall():
    from clawbot.business_cycle_runner import BusinessCycleRunner
    store = MagicMock()
    store.update_metadata = AsyncMock()
    store.update_fitness = AsyncMock()
    pool = MagicMock()
    pool.complete = AsyncMock(return_value=json.dumps({
        "action": "dev_to_publish", "title": "X", "body_markdown": "...",
    }))
    bus = MagicMock()
    bus.publish = AsyncMock()
    runner = BusinessCycleRunner(
        store=store, llm_pool=pool, bus=bus,
        load_skill_catalog=lambda: [],
    )
    biz = _make_business(business_id="biz_test_42")
    produced = await runner.run_one_cycle(biz)
    assert produced is True
    assert runner.artifact_count == 1
    # Stall counter reset to 0 + last_cycle_artifact=True
    store.update_metadata.assert_called()
    update_call = store.update_metadata.call_args
    assert update_call.kwargs["business_id"] == "biz_test_42"
    assert update_call.kwargs["updates"]["artifact_stall_count"] == 0
    assert update_call.kwargs["updates"]["last_cycle_artifact"] is True
    # Action was published with business_id stamped + chain_id present
    bus.publish.assert_called_once()
    topic, payload = bus.publish.call_args.args
    assert topic == "business.directive", (
        f"must use shared business.directive topic so router picks up; got {topic!r}"
    )
    assert payload.get("chain_id"), "chain_id required for CAG depth-0 record"
    data = json.loads(payload["response"])
    assert data["business_id"] == "biz_test_42"


@pytest.mark.asyncio
async def test_cycle_with_wait_action_bumps_stall():
    from clawbot.business_cycle_runner import BusinessCycleRunner
    store = MagicMock()
    store.update_metadata = AsyncMock()
    store.update_fitness = AsyncMock()
    pool = MagicMock()
    pool.complete = AsyncMock(return_value='{"action": "wait"}')
    bus = MagicMock()
    bus.publish = AsyncMock()
    runner = BusinessCycleRunner(
        store=store, llm_pool=pool, bus=bus, load_skill_catalog=lambda: [],
    )
    biz = _make_business(metadata={"artifact_stall_count": 1})
    produced = await runner.run_one_cycle(biz)
    assert produced is False
    update_call = store.update_metadata.call_args
    assert update_call.kwargs["updates"]["artifact_stall_count"] == 2
    bus.publish.assert_not_called()


@pytest.mark.asyncio
async def test_cycle_with_llm_error_stalls_gracefully():
    """LLM error must NOT crash the loop — just bump stall and move on."""
    from clawbot.business_cycle_runner import BusinessCycleRunner
    store = MagicMock()
    store.update_metadata = AsyncMock()
    store.update_fitness = AsyncMock()
    pool = MagicMock()
    pool.complete = AsyncMock(side_effect=RuntimeError("rate limit"))
    bus = MagicMock()
    bus.publish = AsyncMock()
    runner = BusinessCycleRunner(
        store=store, llm_pool=pool, bus=bus, load_skill_catalog=lambda: [],
    )
    biz = _make_business()
    produced = await runner.run_one_cycle(biz)
    assert produced is False
    bus.publish.assert_not_called()


@pytest.mark.asyncio
async def test_cycle_with_garbage_llm_response_stalls():
    from clawbot.business_cycle_runner import BusinessCycleRunner
    store = MagicMock()
    store.update_metadata = AsyncMock()
    store.update_fitness = AsyncMock()
    pool = MagicMock()
    pool.complete = AsyncMock(return_value="here is some prose with no JSON at all")
    bus = MagicMock()
    bus.publish = AsyncMock()
    runner = BusinessCycleRunner(
        store=store, llm_pool=pool, bus=bus, load_skill_catalog=lambda: [],
    )
    biz = _make_business()
    produced = await runner.run_one_cycle(biz)
    assert produced is False


@pytest.mark.asyncio
async def test_cycle_non_artifact_action_dispatches_but_bumps_stall():
    """An action that's NOT in ARTIFACT_ACTIONS (e.g. llm_complete) still
    gets dispatched, but counts as stall — narration doesn't reset the timer."""
    from clawbot.business_cycle_runner import BusinessCycleRunner
    store = MagicMock()
    store.update_metadata = AsyncMock()
    store.update_fitness = AsyncMock()
    pool = MagicMock()
    pool.complete = AsyncMock(return_value='{"action": "llm_complete", "prompt": "x"}')
    bus = MagicMock()
    bus.publish = AsyncMock()
    runner = BusinessCycleRunner(
        store=store, llm_pool=pool, bus=bus, load_skill_catalog=lambda: [],
    )
    biz = _make_business()
    produced = await runner.run_one_cycle(biz)
    assert produced is False  # llm_complete is not an artifact action
    bus.publish.assert_called_once()  # but still dispatched
    update_call = store.update_metadata.call_args
    assert update_call.kwargs["updates"]["artifact_stall_count"] == 1
