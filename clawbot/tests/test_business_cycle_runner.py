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
    store.recent_skill_calls = AsyncMock(return_value=[])
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
    store.recent_skill_calls = AsyncMock(return_value=[])
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
    store.recent_skill_calls = AsyncMock(return_value=[])
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
    store.recent_skill_calls = AsyncMock(return_value=[])
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


def test_missing_required_params_returns_missing_names_when_registry_populated(monkeypatch):
    """Pre-validation must consult the live skill registry and return the
    list of required params absent from the action data dict."""
    import inspect
    from clawbot.business_cycle_runner import _missing_required_params
    from clawbot import skill_registry as sr

    class _FakeMeta:
        timeout_s = 10
        returns = {"url": "str"}
        cost_estimate_usd = 0.0

    class _FakeSkill:
        meta = _FakeMeta()
        async def run(self, ctx, title: str, body_markdown: str) -> dict:
            return {}

    class _FakeRegistry:
        def __init__(self):
            self._skills = {"dev_to_publish": _FakeSkill()}

    monkeypatch.setattr(sr, "REGISTRY", _FakeRegistry())
    # Missing body_markdown
    missing = _missing_required_params(
        "dev_to_publish",
        {"action": "dev_to_publish", "title": "x", "business_id": "biz_z"},
    )
    assert missing == ["body_markdown"]


def test_missing_required_params_returns_empty_when_all_present(monkeypatch):
    import inspect
    from clawbot.business_cycle_runner import _missing_required_params
    from clawbot import skill_registry as sr

    class _Meta:
        timeout_s = 10
        returns = {"url": "str"}
        cost_estimate_usd = 0.0

    class _FakeSkill:
        meta = _Meta()
        async def run(self, ctx, title: str, body_markdown: str) -> dict:
            return {}

    class _FakeRegistry:
        def __init__(self):
            self._skills = {"dev_to_publish": _FakeSkill()}

    monkeypatch.setattr(sr, "REGISTRY", _FakeRegistry())
    missing = _missing_required_params(
        "dev_to_publish",
        {"action": "dev_to_publish", "title": "x", "body_markdown": "y"},
    )
    assert missing == []


def test_missing_required_params_returns_empty_when_skill_unknown(monkeypatch):
    """Unknown skill → empty list. We let dispatch happen and the downstream
    handler decides (registry will fail with 'unknown skill' which we now record)."""
    from clawbot.business_cycle_runner import _missing_required_params
    from clawbot import skill_registry as sr

    class _FakeRegistry:
        _skills: dict = {}

    monkeypatch.setattr(sr, "REGISTRY", _FakeRegistry())
    assert _missing_required_params("nope_skill", {"action": "nope_skill"}) == []


@pytest.mark.asyncio
async def test_cycle_pre_validates_action_and_stalls_on_missing_param(monkeypatch):
    """End-to-end: LLM returns malformed action → pre-validation catches it
    → no bus.publish → stall counter increments."""
    from clawbot.business_cycle_runner import BusinessCycleRunner
    from clawbot import skill_registry as sr

    class _Meta:
        timeout_s = 10
        returns = {"url": "str"}
        cost_estimate_usd = 0.0

    class _FakeSkill:
        meta = _Meta()
        async def run(self, ctx, title: str, body_markdown: str) -> dict:
            return {}

    class _FakeRegistry:
        def __init__(self):
            self._skills = {"dev_to_publish": _FakeSkill()}
            self._stats_db = None  # no DB for synthetic-failure path

    monkeypatch.setattr(sr, "REGISTRY", _FakeRegistry())

    store = MagicMock()
    store.update_metadata = AsyncMock()
    store.update_fitness = AsyncMock()
    store.recent_skill_calls = AsyncMock(return_value=[])
    pool = MagicMock()
    pool.complete = AsyncMock(return_value=json.dumps({
        "action": "dev_to_publish", "title": "X",  # missing body_markdown
    }))
    bus = MagicMock()
    bus.publish = AsyncMock()
    runner = BusinessCycleRunner(
        store=store, llm_pool=pool, bus=bus, load_skill_catalog=lambda: [],
    )
    biz = _make_business()
    produced = await runner.run_one_cycle(biz)
    assert produced is False
    bus.publish.assert_not_called(), "must NOT dispatch a doomed action"
    update_call = store.update_metadata.call_args
    assert update_call.kwargs["updates"]["artifact_stall_count"] == 1


@pytest.mark.asyncio
async def test_cycle_does_not_credit_artifact_when_skill_silently_failed(monkeypatch):
    """Z3.5 critical regression: a publisher returning {"ok": False, ...}
    with no credentials used to credit artifact + reset stall. Now the
    cycle runner polls skill_calls; if no successful row materialises,
    stall increments and the LLM sees the failure next cycle."""
    from clawbot.business_cycle_runner import BusinessCycleRunner
    from clawbot import skill_registry as sr

    # Registry needs the dispatched action to exist so pre-validate passes
    class _Meta:
        timeout_s = 10
        returns = {"ok": "bool", "url": "str"}
        cost_estimate_usd = 0.0

    class _FakeSkill:
        meta = _Meta()
        async def run(self, ctx, title: str, body_markdown: str) -> dict:
            return {"ok": False, "url": ""}

    class _FakeRegistry:
        def __init__(self):
            self._skills = {"dev_to_publish": _FakeSkill()}
            self._stats_db = None

    monkeypatch.setattr(sr, "REGISTRY", _FakeRegistry())

    # Pool that always returns "no skill_calls row found" — simulates the
    # silently-failed publish (registry's call hasn't recorded anything new)
    pool = MagicMock()
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=None)  # poll always finds nothing
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=None)
    pool.acquire = MagicMock(return_value=cm)

    store = MagicMock()
    store._pool = pool
    store.update_metadata = AsyncMock()
    store.update_fitness = AsyncMock()
    store.recent_skill_calls = AsyncMock(return_value=[])
    llm = MagicMock()
    llm.complete = AsyncMock(return_value=json.dumps({
        "action": "dev_to_publish", "title": "X", "body_markdown": "...",
    }))
    bus = MagicMock()
    bus.publish = AsyncMock()
    runner = BusinessCycleRunner(
        store=store, llm_pool=llm, bus=bus, load_skill_catalog=lambda: [],
    )
    # Make the poll fast so the test doesn't take 8s
    biz = _make_business()
    # Patch the helper's wait/poll defaults for speed
    original = runner._await_skill_success
    async def fast_await(**kwargs):
        return await original(**{**kwargs, "max_wait_s": 0.2, "poll_s": 0.05})
    runner._await_skill_success = fast_await
    produced = await runner.run_one_cycle(biz)
    assert produced is False, (
        "must NOT credit artifact when no successful skill_calls row appeared"
    )
    bus.publish.assert_called_once()  # dispatch DID happen
    # Stall must have incremented
    update_call = store.update_metadata.call_args
    assert update_call.kwargs["updates"]["artifact_stall_count"] == 1


@pytest.mark.asyncio
async def test_cycle_credits_artifact_when_successful_skill_row_appears(monkeypatch):
    """Inverse: if the poll finds a successful row, mark artifact as before."""
    from clawbot.business_cycle_runner import BusinessCycleRunner
    from clawbot import skill_registry as sr

    class _Meta:
        timeout_s = 10
        returns = {"ok": "bool", "url": "str"}
        cost_estimate_usd = 0.0

    class _FakeSkill:
        meta = _Meta()
        async def run(self, ctx, title: str, body_markdown: str) -> dict:
            return {"ok": True, "url": "https://posted"}

    class _FakeRegistry:
        def __init__(self):
            self._skills = {"dev_to_publish": _FakeSkill()}
            self._stats_db = None

    monkeypatch.setattr(sr, "REGISTRY", _FakeRegistry())

    pool = MagicMock()
    conn = MagicMock()
    # Poll finds a successful row immediately
    conn.fetchrow = AsyncMock(return_value={"id": 99, "ok": True})
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=None)
    pool.acquire = MagicMock(return_value=cm)

    store = MagicMock()
    store._pool = pool
    store.update_metadata = AsyncMock()
    store.update_fitness = AsyncMock()
    store.recent_skill_calls = AsyncMock(return_value=[])
    llm = MagicMock()
    llm.complete = AsyncMock(return_value=json.dumps({
        "action": "dev_to_publish", "title": "X", "body_markdown": "...",
    }))
    bus = MagicMock()
    bus.publish = AsyncMock()
    runner = BusinessCycleRunner(
        store=store, llm_pool=llm, bus=bus, load_skill_catalog=lambda: [],
    )
    biz = _make_business()
    produced = await runner.run_one_cycle(biz)
    assert produced is True
    update_call = store.update_metadata.call_args
    assert update_call.kwargs["updates"]["artifact_stall_count"] == 0


@pytest.mark.asyncio
async def test_cycle_loads_recent_skill_calls_into_prompt(monkeypatch):
    """The LLM must see its own prior failures. run_one_cycle calls
    store.recent_skill_calls and passes the result to the renderer."""
    from clawbot.business_cycle_runner import BusinessCycleRunner
    captured_recent = []

    def fake_render(*, business, recent_actions, recent_skill_results, skill_catalog):
        captured_recent.extend(recent_actions)
        return "rendered prompt"

    monkeypatch.setattr(
        "clawbot.business_cycle_runner.render_business_prompt", fake_render,
    )
    store = MagicMock()
    store.update_metadata = AsyncMock()
    store.update_fitness = AsyncMock()
    store.recent_skill_calls = AsyncMock(return_value=[
        {"skill_name": "mastodon_post", "ok": False,
         "error": "missing required param: status", "called_at": None},
    ])
    pool = MagicMock()
    pool.complete = AsyncMock(return_value='{"action": "wait"}')
    bus = MagicMock()
    bus.publish = AsyncMock()
    runner = BusinessCycleRunner(
        store=store, llm_pool=pool, bus=bus, load_skill_catalog=lambda: [],
    )
    biz = _make_business()
    await runner.run_one_cycle(biz)
    store.recent_skill_calls.assert_awaited_once()
    assert captured_recent and captured_recent[0]["skill_name"] == "mastodon_post"


@pytest.mark.asyncio
async def test_cycle_non_artifact_action_dispatches_but_bumps_stall():
    """An action that's NOT in ARTIFACT_ACTIONS (e.g. llm_complete) still
    gets dispatched, but counts as stall — narration doesn't reset the timer."""
    from clawbot.business_cycle_runner import BusinessCycleRunner
    store = MagicMock()
    store.update_metadata = AsyncMock()
    store.update_fitness = AsyncMock()
    store.recent_skill_calls = AsyncMock(return_value=[])
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
