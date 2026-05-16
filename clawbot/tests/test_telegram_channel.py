"""Tests for the Telegram outbound + inbound channels."""
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from clawbot.escalation import Escalation
from clawbot.telegram_channel import (
    TelegramSender, TelegramReceiver, _ESC_TAG_RE, _SLASH_REPLY_RE,
)


def _esc(**overrides) -> Escalation:
    base = dict(
        id="abc123def456",
        ts="2026-05-16T12:00:00+00:00",
        severity="request",
        from_agent="cto",
        summary="IR35 PDF ready",
        detail="Upload to gumroad",
        correlation_id="",
    )
    base.update(overrides)
    return Escalation(**base)


# ── Init validation ─────────────────────────────────────────────────────────


def test_sender_requires_both_token_and_chat_id():
    with pytest.raises(ValueError):
        TelegramSender(bot_token="", chat_id="123")
    with pytest.raises(ValueError):
        TelegramSender(bot_token="abc", chat_id="")


def test_receiver_requires_both_token_and_chat_id(tmp_path):
    with pytest.raises(ValueError):
        TelegramReceiver(bot_token="", chat_id="123", metrics_dir=tmp_path)


# ── Outbound: TelegramSender ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_posts_to_sendmessage_endpoint():
    sender = TelegramSender(bot_token="TOKEN", chat_id="42")
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json = MagicMock(return_value={"ok": True, "result": {"message_id": 7}})
    with patch("httpx.AsyncClient") as ctx:
        ctx.return_value.__aenter__.return_value.post = AsyncMock(return_value=fake_resp)
        msg_id = await sender.send_escalation(_esc())
    assert msg_id == 7
    post_call = ctx.return_value.__aenter__.return_value.post.call_args
    url = post_call.args[0]
    payload = post_call.kwargs["json"]
    assert "bot TOKEN/sendMessage".replace(" ", "") in url.replace(" ", "")
    assert payload["chat_id"] == "42"
    assert "[esc:abc123def456]" in payload["text"]
    assert payload["parse_mode"] == "HTML"


@pytest.mark.asyncio
async def test_send_urgent_uses_alarm_format():
    sender = TelegramSender(bot_token="t", chat_id="1")
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json = MagicMock(return_value={"ok": True, "result": {"message_id": 1}})
    with patch("httpx.AsyncClient") as ctx:
        ctx.return_value.__aenter__.return_value.post = AsyncMock(return_value=fake_resp)
        await sender.send_escalation(_esc(severity="urgent"))
    text = ctx.return_value.__aenter__.return_value.post.call_args.kwargs["json"]["text"]
    assert "🚨" in text  # alarm emoji on urgent
    assert "urgent" in text.lower()


@pytest.mark.asyncio
async def test_send_request_uses_casual_format():
    """Request severity should feel like a chat message, not a sysadmin alert."""
    sender = TelegramSender(bot_token="t", chat_id="1")
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json = MagicMock(return_value={"ok": True, "result": {"message_id": 1}})
    with patch("httpx.AsyncClient") as ctx:
        ctx.return_value.__aenter__.return_value.post = AsyncMock(return_value=fake_resp)
        await sender.send_escalation(_esc(severity="request", from_agent="cto"))
    text = ctx.return_value.__aenter__.return_value.post.call_args.kwargs["json"]["text"]
    assert "your CTO" in text  # friendly role name, not "Clawbot REQUEST"
    assert "REQUEST" not in text  # no formal title
    assert "hit reply" in text  # casual reply hint


@pytest.mark.asyncio
async def test_send_escapes_html_in_summary_and_detail():
    sender = TelegramSender(bot_token="t", chat_id="1")
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json = MagicMock(return_value={"ok": True, "result": {"message_id": 1}})
    with patch("httpx.AsyncClient") as ctx:
        ctx.return_value.__aenter__.return_value.post = AsyncMock(return_value=fake_resp)
        await sender.send_escalation(_esc(summary="<script>alert(1)</script>", detail="x > y & z < q"))
    text = ctx.return_value.__aenter__.return_value.post.call_args.kwargs["json"]["text"]
    assert "<script>" not in text
    assert "&lt;script&gt;" in text
    assert "&amp;" in text


@pytest.mark.asyncio
async def test_send_returns_none_on_http_error_without_raising():
    sender = TelegramSender(bot_token="t", chat_id="1")
    with patch("httpx.AsyncClient") as ctx:
        ctx.return_value.__aenter__.return_value.post = AsyncMock(
            side_effect=httpx.ConnectError("network gone")
        )
        result = await sender.send_escalation(_esc())
    assert result is None


@pytest.mark.asyncio
async def test_send_returns_none_when_api_not_ok():
    sender = TelegramSender(bot_token="t", chat_id="1")
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json = MagicMock(return_value={"ok": False, "description": "bot blocked"})
    with patch("httpx.AsyncClient") as ctx:
        ctx.return_value.__aenter__.return_value.post = AsyncMock(return_value=fake_resp)
        result = await sender.send_escalation(_esc())
    assert result is None


# ── Inbound: TelegramReceiver parsing ───────────────────────────────────────


def test_slash_reply_regex_extracts_id_and_text():
    m = _SLASH_REPLY_RE.match("/reply abc123def456 yes, upload it now")
    assert m is not None
    assert m.group(1) == "abc123def456"
    assert m.group(2).strip() == "yes, upload it now"


def test_slash_reply_regex_handles_multiline_text():
    m = _SLASH_REPLY_RE.match("/reply abc123def456 line one\nline two")
    assert m is not None
    assert "line two" in m.group(2)


def test_slash_reply_regex_rejects_no_id():
    assert _SLASH_REPLY_RE.match("/reply just text") is None


def test_esc_tag_regex_finds_id_in_message_text():
    text = "🙋 Clawbot REQUEST — from cto\n[esc:abc123def456]\n\nIR35 PDF ready..."
    m = _ESC_TAG_RE.search(text)
    assert m is not None
    assert m.group(1) == "abc123def456"


def test_esc_tag_regex_returns_none_without_tag():
    assert _ESC_TAG_RE.search("regular text without tag") is None


def _receiver(tmp_path: Path) -> TelegramReceiver:
    return TelegramReceiver(bot_token="t", chat_id="42", metrics_dir=tmp_path)


def test_classify_message_via_slash_command(tmp_path):
    r = _receiver(tmp_path)
    message = {"text": "/reply abc123def456 do it"}
    result = r._classify_message(message)
    assert result == ("reply", ("abc123def456", "do it"))


def test_classify_message_via_reply_to_message(tmp_path):
    r = _receiver(tmp_path)
    message = {
        "text": "yes, please proceed",
        "reply_to_message": {"text": "[esc:abc123def456] something"},
    }
    result = r._classify_message(message)
    assert result == ("reply", ("abc123def456", "yes, please proceed"))


def test_classify_message_unrouted_becomes_chat(tmp_path):
    """Free-form messages (no /reply, no reply-to-tag) route to chat — this is
    how the operator initiates a conversation."""
    r = _receiver(tmp_path)
    result = r._classify_message({"text": "hey, what's revenue today?"})
    assert result == ("chat", "hey, what's revenue today?")


def test_classify_message_empty_returns_none(tmp_path):
    r = _receiver(tmp_path)
    assert r._classify_message({}) is None
    assert r._classify_message({"text": ""}) is None


# ── Inbound: auth + reply writing ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_unauthorised_chat_id_is_ignored(tmp_path):
    r = _receiver(tmp_path)
    updates = [{
        "update_id": 99,
        "message": {
            "chat": {"id": 999},  # not the configured 42
            "text": "/reply abc123def456 sneaky",
        },
    }]
    await r._process_updates(updates)
    # No reply file should be created
    replies_path = tmp_path / "escalation_replies.jsonl"
    assert not replies_path.exists()
    # Offset still advances so we don't reprocess
    assert (tmp_path / "telegram_offset").read_text().strip() == "100"


@pytest.mark.asyncio
async def test_authorised_slash_reply_writes_to_replies_file(tmp_path):
    r = _receiver(tmp_path)
    updates = [{
        "update_id": 5,
        "message": {
            "chat": {"id": 42},
            "text": "/reply abc123def456 looks good",
        },
    }]
    await r._process_updates(updates)
    replies_path = tmp_path / "escalation_replies.jsonl"
    assert replies_path.exists()
    line = json.loads(replies_path.read_text().strip())
    assert line["id"] == "abc123def456"
    assert line["reply"] == "looks good"


@pytest.mark.asyncio
async def test_reply_to_message_writes_to_replies_file(tmp_path):
    r = _receiver(tmp_path)
    updates = [{
        "update_id": 5,
        "message": {
            "chat": {"id": 42},
            "text": "approved",
            "reply_to_message": {"text": "[esc:abc123def456] please upload"},
        },
    }]
    await r._process_updates(updates)
    line = json.loads((tmp_path / "escalation_replies.jsonl").read_text().strip())
    assert line["id"] == "abc123def456"
    assert line["reply"] == "approved"


@pytest.mark.asyncio
async def test_offset_persists_max_update_id_plus_one(tmp_path):
    """Telegram protocol: next offset = highest update_id seen + 1, to ack receipt."""
    r = _receiver(tmp_path)
    updates = [
        {"update_id": 7, "message": {"chat": {"id": 42}, "text": "hi"}},
        {"update_id": 12, "message": {"chat": {"id": 42}, "text": "hello"}},
    ]
    await r._process_updates(updates)
    assert (tmp_path / "telegram_offset").read_text().strip() == "13"


def test_load_offset_returns_zero_when_missing(tmp_path):
    r = _receiver(tmp_path)
    assert r._load_offset() == 0
