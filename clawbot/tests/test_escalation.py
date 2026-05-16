import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from clawbot.escalation import (
    Escalation, EscalationStore, ReplyStore, OperatorReply,
    escalate, write_operator_reply, ESCALATION_TOPIC,
)


def _esc(**overrides) -> Escalation:
    base = dict(
        id="abc123def456",
        ts="2026-05-16T12:00:00+00:00",
        severity="request",
        from_agent="cto",
        summary="IR35 PDF ready for upload",
        detail="See /metrics/escalations/abc123def456.json",
        correlation_id="",
    )
    base.update(overrides)
    return Escalation(**base)


# ── Escalation writer ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_escalate_publishes_to_bus():
    bus = MagicMock()
    bus.publish = AsyncMock(return_value="1-0")
    esc = await escalate(
        bus, severity="warning", summary="weird thing",
        detail="thing detail", from_agent="meta",
    )
    bus.publish.assert_called_once()
    topic, payload = bus.publish.call_args.args
    assert topic == ESCALATION_TOPIC
    assert payload["severity"] == "warning"
    assert payload["from_agent"] == "meta"
    assert payload["id"] == esc.id
    assert len(esc.id) == 12  # uuid hex slice


@pytest.mark.asyncio
async def test_escalate_truncates_oversized_fields():
    bus = MagicMock()
    bus.publish = AsyncMock()
    esc = await escalate(
        bus, severity="info",
        summary="x" * 500, detail="y" * 10_000,
        from_agent="ceo",
    )
    assert len(esc.summary) == 300
    assert len(esc.detail) == 4000


@pytest.mark.asyncio
async def test_escalate_preserves_correlation_id():
    bus = MagicMock()
    bus.publish = AsyncMock()
    esc = await escalate(
        bus, severity="info", summary="x", detail="y",
        from_agent="ceo", correlation_id="trace-42",
    )
    assert esc.correlation_id == "trace-42"


# ── EscalationStore persistence ─────────────────────────────────────────────


def test_persist_writes_jsonl_and_detail(tmp_path):
    store = EscalationStore(metrics_dir=tmp_path)
    esc = _esc()
    store.persist(esc)

    log_path = tmp_path / "escalations.jsonl"
    detail_path = tmp_path / "escalations" / "abc123def456.json"
    assert log_path.exists()
    assert detail_path.exists()
    line = json.loads(log_path.read_text().strip())
    assert line["id"] == "abc123def456"


def test_persist_appends_not_overwrites(tmp_path):
    store = EscalationStore(metrics_dir=tmp_path)
    store.persist(_esc(id="111111111111"))
    store.persist(_esc(id="222222222222"))
    lines = (tmp_path / "escalations.jsonl").read_text().splitlines()
    assert len(lines) == 2


def test_list_recent_returns_chronological(tmp_path):
    store = EscalationStore(metrics_dir=tmp_path)
    for i in range(5):
        store.persist(_esc(id=f"{i:012d}", summary=f"esc {i}"))
    recent = store.list_recent(limit=3)
    assert len(recent) == 3
    assert recent[0].summary == "esc 2"
    assert recent[-1].summary == "esc 4"


# ── ntfy push ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ntfy_skipped_when_topic_unconfigured(tmp_path):
    store = EscalationStore(metrics_dir=tmp_path, ntfy_topic="")
    with patch("httpx.AsyncClient") as ctx:
        result = await store.push_ntfy(_esc())
    assert result is False
    ctx.assert_not_called()


@pytest.mark.asyncio
async def test_ntfy_posts_to_configured_topic(tmp_path):
    store = EscalationStore(metrics_dir=tmp_path, ntfy_topic="my-clawbot-topic")
    fake_response = MagicMock()
    fake_response.status_code = 200
    with patch("httpx.AsyncClient") as ctx:
        ctx.return_value.__aenter__.return_value.post = AsyncMock(return_value=fake_response)
        result = await store.push_ntfy(_esc())
    assert result is True
    post_call = ctx.return_value.__aenter__.return_value.post.call_args
    url = post_call.args[0]
    assert "my-clawbot-topic" in url
    headers = post_call.kwargs["headers"]
    assert "Clawbot" in headers["Title"]
    assert headers["Priority"] == "default"  # severity "request" → default priority


@pytest.mark.asyncio
async def test_ntfy_returns_false_on_failure_without_raising(tmp_path):
    """ntfy push failure must NOT break the bus consumer — persistence already happened."""
    import httpx
    store = EscalationStore(metrics_dir=tmp_path, ntfy_topic="my-topic")
    with patch("httpx.AsyncClient") as ctx:
        ctx.return_value.__aenter__.return_value.post = AsyncMock(
            side_effect=httpx.ConnectError("ntfy.sh unreachable")
        )
        result = await store.push_ntfy(_esc())
    assert result is False  # graceful — not an exception


@pytest.mark.asyncio
async def test_ntfy_priority_escalates_with_severity(tmp_path):
    store = EscalationStore(metrics_dir=tmp_path, ntfy_topic="t")
    captures = []

    async def fake_post(url, **kwargs):
        captures.append(kwargs["headers"]["Priority"])
        r = MagicMock()
        r.status_code = 200
        return r

    with patch("httpx.AsyncClient") as ctx:
        ctx.return_value.__aenter__.return_value.post = AsyncMock(side_effect=fake_post)
        await store.push_ntfy(_esc(severity="info"))
        await store.push_ntfy(_esc(severity="urgent"))
    assert captures == ["low", "urgent"]


# ── Reply store ─────────────────────────────────────────────────────────────


def test_reply_store_returns_empty_when_no_replies(tmp_path):
    rs = ReplyStore(metrics_dir=tmp_path)
    assert rs.drain_new_replies() == []


@pytest.mark.asyncio
async def test_reply_round_trip(tmp_path):
    await write_operator_reply(tmp_path, "abc123def456", "yes, do the IR35 thing")
    rs = ReplyStore(metrics_dir=tmp_path)
    replies = rs.drain_new_replies()
    assert len(replies) == 1
    assert replies[0].escalation_id == "abc123def456"
    assert "IR35" in replies[0].reply


@pytest.mark.asyncio
async def test_drain_is_idempotent(tmp_path):
    """Once drained, the same reply is not republished on subsequent calls."""
    await write_operator_reply(tmp_path, "id-1", "reply A")
    rs = ReplyStore(metrics_dir=tmp_path)
    first = rs.drain_new_replies()
    second = rs.drain_new_replies()
    assert len(first) == 1
    assert second == []


@pytest.mark.asyncio
async def test_drain_picks_up_new_replies_after_offset(tmp_path):
    await write_operator_reply(tmp_path, "id-1", "first")
    rs = ReplyStore(metrics_dir=tmp_path)
    rs.drain_new_replies()
    await write_operator_reply(tmp_path, "id-2", "second")
    new_replies = rs.drain_new_replies()
    assert len(new_replies) == 1
    assert new_replies[0].reply == "second"


def test_drain_skips_malformed_lines(tmp_path):
    path = tmp_path / "escalation_replies.jsonl"
    path.write_text(
        '{"id": "good", "ts": "2026-01-01", "reply": "ok"}\n'
        'garbage line\n'
        '{"id": "also-good", "ts": "2026-01-01", "reply": "fine"}\n',
        encoding="utf-8",
    )
    rs = ReplyStore(metrics_dir=tmp_path)
    replies = rs.drain_new_replies()
    assert len(replies) == 2
    assert {r.escalation_id for r in replies} == {"good", "also-good"}
