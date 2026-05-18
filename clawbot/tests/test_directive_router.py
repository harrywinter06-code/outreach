import json
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock
from clawbot.directive_router import DirectiveRouter


def make_bus(messages_by_topic: dict):
    bus = MagicMock()
    async def fake_read(topic, consumer_id, count=10, block_ms=5000):
        return messages_by_topic.get(topic, [])
    bus.read = fake_read
    bus.ack = AsyncMock()
    bus.publish = AsyncMock()
    bus.publish_inbox = AsyncMock()
    return bus


def make_directive_msg(action: str, directive: str = "test", chain_id: str | None = None, **extra):
    chain_id = chain_id or str(uuid.uuid4())
    payload = {"action": action, "directive": directive, "priority": "high", **extra}
    return {
        "_id": "1-1",
        "response": json.dumps(payload),
        "chain_id": chain_id,
        "ts": "2026-01-01T00:00:00Z",
    }


def make_router(bus, causal_store=None, task_store=None, brain=None):
    from clawbot.directive_router import DirectiveRouter
    cs = causal_store or MagicMock()
    if causal_store is None:
        cs.record_event = AsyncMock(return_value=str(uuid.uuid4()))
    ts = task_store or MagicMock()
    if task_store is None:
        ts.create_task = MagicMock(return_value=str(uuid.uuid4()))
    registry = MagicMock()
    # registry.get must be async and return a truthy object so assign_task
    # validation passes. Tasks assigned to non-existent agents raise ValueError.
    registry.get = AsyncMock(return_value=MagicMock())
    return DirectiveRouter(
        bus=bus, causal_store=cs, registry=registry,
        agent_factory=MagicMock(), task_store=ts,
        metrics_dir=MagicMock(), brain=brain,
    )


async def test_acks_on_successful_dispatch():
    msg = make_directive_msg("message", directive="hello", target="worker-001")
    bus = make_bus({"ceo.directive": [msg]})
    router = make_router(bus)
    await router._poll_once()
    bus.ack.assert_called_once_with("ceo.directive", "1-1")


async def test_does_not_ack_when_causal_record_fails():
    msg = make_directive_msg("message", target="worker-001")
    bus = make_bus({"ceo.directive": [msg]})
    cs = MagicMock()
    cs.record_event = AsyncMock(side_effect=RuntimeError("db down"))
    router = make_router(bus, causal_store=cs)
    await router._poll_once()
    bus.ack.assert_not_called()


async def test_acks_malformed_json_immediately():
    msg = {"_id": "2-2", "response": "not json", "chain_id": str(uuid.uuid4()), "ts": ""}
    bus = make_bus({"ceo.directive": [msg]})
    router = make_router(bus)
    await router._poll_once()
    bus.ack.assert_called_once_with("ceo.directive", "2-2")


async def test_records_two_causal_events_for_known_action():
    chain_id = str(uuid.uuid4())
    msg = make_directive_msg("message", chain_id=chain_id, target="worker-001")
    bus = make_bus({"ceo.directive": [msg]})
    cs = MagicMock()
    cs.record_event = AsyncMock(return_value=str(uuid.uuid4()))
    router = make_router(bus, causal_store=cs)
    await router._poll_once()
    assert cs.record_event.call_count == 2
    depths = [c.kwargs["causal_depth"] for c in cs.record_event.call_args_list]
    assert 0 in depths and 1 in depths


async def test_assign_task_creates_task():
    chain_id = str(uuid.uuid4())
    msg = make_directive_msg("assign_task", chain_id=chain_id,
                             title="Write guide", description="details",
                             assigned_to="worker-001")
    bus = make_bus({"ceo.directive": [msg]})
    ts = MagicMock()
    ts.create_task = MagicMock(return_value=str(uuid.uuid4()))
    router = make_router(bus, task_store=ts)
    await router._poll_once()
    ts.create_task.assert_called_once()
    kwargs = ts.create_task.call_args.kwargs
    assert kwargs["assigned_to"] == "worker-001"
    assert kwargs["chain_id"] == chain_id


async def test_message_action_publishes_to_inbox():
    msg = make_directive_msg("message", target="worker-001", message="do this now")
    bus = make_bus({"ceo.directive": [msg]})
    router = make_router(bus)
    await router._poll_once()
    bus.publish_inbox.assert_called_once()
    args = bus.publish_inbox.call_args
    assert args.args[0] == "worker-001"


async def test_unknown_action_acked_without_handler():
    msg = make_directive_msg("unknown_action_xyz")
    bus = make_bus({"ceo.directive": [msg]})
    router = make_router(bus)
    await router._poll_once()
    bus.ack.assert_called_once()


async def test_handle_skill_call_threads_stripe_secret_key_to_make_live_ctx():
    """Regression: stripe_secret_key must be passed so payments skills work in production."""
    from unittest.mock import patch
    from pathlib import Path

    bus = MagicMock()
    bus.ack = AsyncMock()
    bus.publish_inbox = AsyncMock()

    captured_kwargs = {}
    def fake_make_live_ctx(**kwargs):
        captured_kwargs.update(kwargs)
        # Return a noop-shaped object so call() doesn't blow up downstream
        from clawbot.skill_ctx import make_noop_ctx
        return make_noop_ctx(caller_id=kwargs["caller_id"], budget_usd=kwargs["budget_usd"])

    # REGISTRY must be set; patch it.
    fake_registry = MagicMock()
    fake_registry.call = AsyncMock(return_value=MagicMock(
        ok=True, result={"ok": True}, error=None, skill_name="test_skill", latency_ms=10,
    ))
    fake_registry.is_canary = MagicMock(return_value=False)
    fake_registry._record_live_call = MagicMock()
    fake_meta = MagicMock()
    fake_meta.requires_approval = False  # don't enter approval gate in this test
    fake_registry.get_meta = MagicMock(return_value=fake_meta)

    router = DirectiveRouter(
        bus=bus,
        causal_store=MagicMock(record_event=AsyncMock()),
        registry=MagicMock(),
        agent_factory=MagicMock(),
        task_store=MagicMock(),
        metrics_dir=Path("/tmp/test_metrics"),
        brain=None,
    )

    with patch("clawbot.skill_ctx.make_live_ctx", side_effect=fake_make_live_ctx):
        with patch("clawbot.skill_registry.REGISTRY", fake_registry):
            with patch("clawbot.config.settings") as fake_settings:
                fake_settings.stripe_secret_key = "sk_test_THREAD_ME"
                fake_settings.tavily_api_key = ""
                fake_settings.firecrawl_api_key = ""
                fake_settings.accounts_vault_key = ""
                fake_settings.accounts_db_path = "data/accounts.db"
                fake_settings.imap_host = ""
                fake_settings.imap_port = 993
                fake_settings.imap_user = ""
                fake_settings.imap_password = ""
                fake_settings.email_domain = ""
                await router._handle_skill_call(
                    skill_name="test_skill", params={}, chain_id="c-001", from_agent="cmo",
                )

    assert captured_kwargs.get("stripe_secret_key") == "sk_test_THREAD_ME", (
        f"stripe_secret_key not threaded to make_live_ctx; got: {list(captured_kwargs.keys())}"
    )


@pytest.mark.asyncio
async def test_requires_approval_skill_publishes_request_and_blocks_on_denial():
    """A requires_approval=True skill must publish operator.approval_request,
    block dispatch, and notify the caller inbox when the operator sends a denial."""
    from unittest.mock import patch, AsyncMock, MagicMock
    from pathlib import Path

    published: list[tuple] = []
    # approval_id captured from the first operator.approval_request publish
    captured_approval_id: list[str] = []

    bus = MagicMock()
    bus.ack = AsyncMock()
    bus.publish_inbox = AsyncMock()

    async def fake_publish(topic, payload):
        published.append((topic, payload))
        if topic == "operator.approval_request":
            captured_approval_id.append(payload["request_id"])

    bus.publish = fake_publish

    # On the first bus.read call, return a denial reply matching the approval_id.
    async def fake_read(topic, consumer_id, count=10, block_ms=1000):
        if topic == "operator.approval_reply" and captured_approval_id:
            return [{"request_id": captured_approval_id[0], "approved": False}]
        return []

    bus.read = fake_read

    fake_meta = MagicMock()
    fake_meta.requires_approval = True

    fake_registry = MagicMock()
    fake_registry.call = AsyncMock()  # must NOT be called on denial
    fake_registry.is_canary = MagicMock(return_value=False)
    fake_registry._record_live_call = MagicMock()
    fake_registry.get_meta = MagicMock(return_value=fake_meta)

    router = DirectiveRouter(
        bus=bus,
        causal_store=MagicMock(record_event=AsyncMock()),
        registry=MagicMock(),
        agent_factory=MagicMock(),
        task_store=MagicMock(),
        metrics_dir=Path("/tmp/test_metrics_approval"),
        brain=None,
    )

    from clawbot.skill_ctx import make_noop_ctx

    def fake_make_live_ctx(**kwargs):
        return make_noop_ctx(caller_id=kwargs["caller_id"], budget_usd=kwargs["budget_usd"])

    with patch("clawbot.skill_ctx.make_live_ctx", side_effect=fake_make_live_ctx), \
         patch("clawbot.skill_registry.REGISTRY", fake_registry), \
         patch("clawbot.config.settings") as fake_settings:
        fake_settings.stripe_secret_key = ""
        fake_settings.stripe_live_mode_enabled = False
        fake_settings.capital_daily_cap_gbp = 100.0
        fake_settings.capital_weekly_cap_gbp = 500.0
        fake_settings.capital_freeze = False
        fake_settings.tavily_api_key = ""
        fake_settings.firecrawl_api_key = ""
        fake_settings.accounts_vault_key = ""
        fake_settings.accounts_db_path = "data/accounts.db"
        fake_settings.imap_host = ""
        fake_settings.imap_port = 993
        fake_settings.imap_user = ""
        fake_settings.imap_password = ""
        fake_settings.email_domain = ""
        fake_settings.gumroad_api_key = ""
        fake_settings.paypal_client_id = ""
        fake_settings.paypal_client_secret = ""
        fake_settings.paypal_environment = "sandbox"
        fake_settings.coinbase_commerce_api_key = ""

        await router._handle_skill_call(
            skill_name="stripe_issue_card", params={"amount": 100},
            chain_id="c-approval", from_agent="ceo",
        )

    # approval_request and escalation must have been published
    topics = [t for t, _ in published]
    assert "operator.approval_request" in topics, (
        f"operator.approval_request not published; published topics: {topics}"
    )
    assert "operator.escalation" in topics, (
        f"operator.escalation not published; published topics: {topics}"
    )

    # REGISTRY.call must NOT have been invoked (denied)
    fake_registry.call.assert_not_called()

    # Caller inbox must have received skill_denied or similar error
    bus.publish_inbox.assert_called_once()
    _, inbox_payload = bus.publish_inbox.call_args.args
    assert (
        inbox_payload.get("kind") == "skill_denied"
        or inbox_payload.get("error") == "operator did not approve"
    ), f"Unexpected inbox payload: {inbox_payload}"
