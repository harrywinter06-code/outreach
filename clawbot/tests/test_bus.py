import json
import pytest
from unittest.mock import AsyncMock
from clawbot.bus import MessageBus, CONSUMER_GROUP


@pytest.fixture
def bus():
    b = MessageBus(redis_url="redis://localhost/0")
    mock_redis = AsyncMock()
    b._redis = mock_redis
    return b


@pytest.mark.asyncio
async def test_publish_writes_to_stream(bus: MessageBus):
    bus._r.xadd = AsyncMock(return_value="1234-0")
    msg_id = await bus.publish("ceo.directive", {"action": "pivot"})
    assert msg_id == "1234-0"
    bus._r.xadd.assert_called_once()
    call_args = bus._r.xadd.call_args
    stream_name = call_args.args[0]
    assert "ceo.directive" in stream_name


@pytest.mark.asyncio
async def test_subscribe_creates_consumer_group(bus: MessageBus):
    bus._r.xgroup_create = AsyncMock()
    await bus.subscribe("ceo.directive")
    bus._r.xgroup_create.assert_called_once()
    args = bus._r.xgroup_create.call_args.args
    assert "ceo.directive" in args[0]
    assert args[1] == CONSUMER_GROUP


@pytest.mark.asyncio
async def test_subscribe_ignores_existing_group(bus: MessageBus):
    bus._r.xgroup_create = AsyncMock(side_effect=Exception("BUSYGROUP Consumer Group name already exists"))
    await bus.subscribe("ceo.directive")  # must not raise


@pytest.mark.asyncio
async def test_subscribe_reraises_other_exceptions(bus: MessageBus):
    bus._r.xgroup_create = AsyncMock(side_effect=ConnectionError("Redis down"))
    with pytest.raises(ConnectionError):
        await bus.subscribe("ceo.directive")


@pytest.mark.asyncio
async def test_read_returns_parsed_payloads(bus: MessageBus):
    payload = {"agent": "cfo", "msg": "budget approved"}
    raw_entry = [
        ("1-0", {"payload": json.dumps(payload), "ts": "2026-01-01T00:00:00+00:00"}),
    ]
    bus._r.xreadgroup = AsyncMock(return_value=[("clawbot:bus:ceo.directive", raw_entry)])

    messages = await bus.read("ceo.directive", consumer_id="ceo-1")
    assert len(messages) == 1
    assert messages[0]["agent"] == "cfo"
    assert messages[0]["_id"] == "1-0"


@pytest.mark.asyncio
async def test_read_auto_subscribes_on_nogroup(bus: MessageBus):
    """If the consumer group doesn't exist, read() creates it and retries.
    Without this, any topic not enumerated in main.py's subscribe loop
    (e.g. operator.approval_reply) crashes _LiveOperator.request_approval."""
    payload = {"approved": True, "request_id": "abc"}
    raw_entry = [
        ("1-0", {"payload": json.dumps(payload), "ts": "2026-01-01T00:00:00+00:00"}),
    ]
    bus._r.xgroup_create = AsyncMock()
    bus._r.xreadgroup = AsyncMock(side_effect=[
        Exception("NOGROUP No such key 'clawbot:bus:operator.approval_reply'"),
        [("clawbot:bus:operator.approval_reply", raw_entry)],
    ])
    messages = await bus.read("operator.approval_reply", consumer_id="approval-abc")
    assert len(messages) == 1
    assert messages[0]["approved"] is True
    bus._r.xgroup_create.assert_called_once()
    assert bus._r.xreadgroup.call_count == 2


@pytest.mark.asyncio
async def test_read_reraises_non_nogroup_errors(bus: MessageBus):
    """ConnectionError is fatal — must not silently retry."""
    bus._r.xreadgroup = AsyncMock(side_effect=ConnectionError("redis down"))
    with pytest.raises(ConnectionError):
        await bus.read("ceo.directive", consumer_id="ceo-1")


@pytest.mark.asyncio
async def test_read_returns_empty_when_no_messages(bus: MessageBus):
    bus._r.xreadgroup = AsyncMock(return_value=None)
    messages = await bus.read("ceo.directive", consumer_id="ceo-1")
    assert messages == []


@pytest.mark.asyncio
async def test_ack_calls_xack(bus: MessageBus):
    bus._r.xack = AsyncMock()
    await bus.ack("ceo.directive", "1234-0")
    bus._r.xack.assert_called_once_with("clawbot:bus:ceo.directive", CONSUMER_GROUP, "1234-0")


@pytest.mark.asyncio
async def test_read_and_ack_acks_all_messages(bus: MessageBus):
    payload = {"x": 1}
    raw_entry = [
        ("1-0", {"payload": json.dumps(payload), "ts": "2026-01-01T00:00:00"}),
        ("1-1", {"payload": json.dumps(payload), "ts": "2026-01-01T00:00:01"}),
    ]
    bus._r.xreadgroup = AsyncMock(return_value=[("stream", raw_entry)])
    bus._r.xack = AsyncMock()

    messages = await bus.read_and_ack("ceo.directive", consumer_id="ceo-1")
    assert len(messages) == 2
    assert bus._r.xack.call_count == 2
