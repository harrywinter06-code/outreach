import json
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock


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
    return DirectiveRouter(
        bus=bus, causal_store=cs, registry=MagicMock(),
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
