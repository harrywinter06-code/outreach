"""Builtin support pack — pack-load + representative call tests."""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

from clawbot.skill_registry import SkillRegistry
from clawbot.skill_ctx import make_noop_ctx

BUILTIN_DIR = Path(__file__).parent.parent / "agents" / "skills" / "_builtin"


def _registry() -> SkillRegistry:
    reg = SkillRegistry(skills_dir=BUILTIN_DIR)
    reg.discover()
    return reg


SUPPORT_SKILLS = {
    "support_send_email_reply",
    "support_assign_ticket",
    "support_canned_response",
    "chat_widget_respond_live",
    "calendar_book_slot",
    "survey_send_nps",
}


def test_support_pack_loads():
    reg = _registry()
    loaded = set(reg.list_names())
    missing = SUPPORT_SKILLS - loaded
    assert not missing, f"missing support skills: {missing}"


def test_support_send_email_reply_routes_to_email():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="support", budget_usd=0.0)
    ctx.email.send = AsyncMock(return_value={"id": "msg_123"})  # type: ignore[method-assign]
    record = asyncio.run(reg.call("support_send_email_reply", {
        "to": "customer@example.com",
        "subject": "Re: your question",
        "body_text": "Thanks for reaching out.",
        "reply_to": "<orig@example.com>",
    }, ctx))
    assert record.ok is True
    assert record.result["id"] == "msg_123"
    assert record.result["ok"] is True
    ctx.email.send.assert_called_once()


def test_chat_widget_respond_publishes_outbound():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="support", budget_usd=0.0)
    ctx.bus.publish = AsyncMock(return_value="msg-abc")  # type: ignore[method-assign]
    record = asyncio.run(reg.call("chat_widget_respond_live", {
        "session_id": "sess_1",
        "text": "Hi, how can I help?",
    }, ctx))
    assert record.ok is True
    assert record.result["message_id"] == "msg-abc"
    topic, payload = ctx.bus.publish.call_args.args
    assert topic == "chat.outbound"
    assert payload["session_id"] == "sess_1"


def test_support_canned_response_returns_top_hit():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="support", budget_usd=0.0)
    ctx.vector.search = AsyncMock(return_value=[  # type: ignore[method-assign]
        {"content": "Try logging out and back in.", "score": 0.91,
         "metadata": {"resolution_reply": "Please clear your cookies and retry."}},
    ])
    record = asyncio.run(reg.call("support_canned_response", {
        "question": "I can't log in",
    }, ctx))
    assert record.ok is True
    assert record.result["suggested_reply"] == "Please clear your cookies and retry."
    assert record.result["match_score"] == 0.91


def test_support_canned_response_empty_when_no_hits():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="support", budget_usd=0.0)
    ctx.vector.search = AsyncMock(return_value=[])  # type: ignore[method-assign]
    record = asyncio.run(reg.call("support_canned_response", {
        "question": "Anything?",
    }, ctx))
    assert record.ok is True
    assert record.result["suggested_reply"] == ""
    assert record.result["match_score"] == 0.0
