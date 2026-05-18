"""Outreach + CRM skill pack: discovery + SQL routing + LLM classification."""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

from clawbot.skill_registry import SkillRegistry
from clawbot.skill_ctx import make_noop_ctx

OUTREACH_DIR = Path(__file__).parent.parent / "agents" / "skills" / "_builtin" / "outreach"


def _registry() -> SkillRegistry:
    reg = SkillRegistry(skills_dir=OUTREACH_DIR)
    reg.discover()
    return reg


def test_outreach_pack_loads():
    reg = _registry()
    names = set(reg.list_names())
    expected = {
        "hunter_find_email", "apollo_search_contacts",
        "email_warmup_send", "email_warmup_inbox_clean",
        "email_send_cold", "email_send_followup_sequence",
        "email_classify_reply", "email_suppress",
        "crm_upsert_lead", "crm_advance_stage", "lead_score",
    }
    missing = expected - names
    assert not missing, f"missing outreach skills: {missing}"


def test_email_classify_reply_parses_json():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    ctx.llm.complete = AsyncMock(return_value='{"label": "positive", "confidence": 0.92}')
    rec = asyncio.run(reg.call("email_classify_reply", {
        "from_addr": "x@y.com", "subject": "re: hi", "body": "Yes, let's talk.",
    }, ctx))
    assert rec.ok, rec.error
    assert rec.result["label"] == "positive"
    assert rec.result["confidence"] == 0.92


def test_email_classify_reply_falls_back_on_garbage():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    ctx.llm.complete = AsyncMock(return_value="no json here")
    rec = asyncio.run(reg.call("email_classify_reply", {
        "from_addr": "x@y.com", "subject": "", "body": "",
    }, ctx))
    assert rec.ok, rec.error
    assert rec.result["label"] == "unclear"
    assert rec.result["confidence"] == 0.0


def test_email_send_cold_blocks_suppressed():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    ctx.sql.query = AsyncMock(return_value=[{"email": "x@y.com"}])  # type: ignore[method-assign]
    ctx.email.send = AsyncMock(return_value={"id": "m1", "ok": True})  # type: ignore[method-assign]
    rec = asyncio.run(reg.call("email_send_cold", {
        "to": "x@y.com", "subject": "hi", "body_text": "hello",
    }, ctx))
    # Z3.5: suppressed sends now return record.ok=False — they're
    # blocked-on-purpose but they're not a successful send. The skill's
    # inner ok=False is now treated as authoritative.
    assert rec.ok is False
    assert rec.result["suppressed"] is True
    assert rec.result["ok"] is False
    ctx.email.send.assert_not_called()


def test_email_send_cold_sends_when_not_suppressed():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    ctx.sql.query = AsyncMock(return_value=[])  # type: ignore[method-assign]
    ctx.email.send = AsyncMock(return_value={"id": "m1", "ok": True})  # type: ignore[method-assign]
    rec = asyncio.run(reg.call("email_send_cold", {
        "to": "fresh@y.com", "subject": "hi", "body_text": "hello",
        "unsubscribe_url": "https://u/u",
    }, ctx))
    assert rec.ok, rec.error
    assert rec.result["suppressed"] is False
    assert rec.result["ok"] is True
    call = ctx.email.send.call_args
    assert "https://u/u" in call.kwargs["body_text"]


def test_email_suppress_upserts():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    ctx.sql.query = AsyncMock(return_value=[])  # type: ignore[method-assign]
    rec = asyncio.run(reg.call("email_suppress", {
        "email": "X@Y.COM", "reason": "bounced",
    }, ctx))
    assert rec.ok, rec.error
    assert rec.result["email"] == "x@y.com"
    ctx.sql.query.assert_called_once()
    sql_arg = ctx.sql.query.call_args.args[0]
    assert "INSERT INTO suppression" in sql_arg
    assert "ON CONFLICT" in sql_arg


def test_crm_upsert_lead_detects_new_vs_existing():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    ctx.sql.query = AsyncMock(side_effect=[[], None])  # type: ignore[method-assign]
    rec = asyncio.run(reg.call("crm_upsert_lead", {
        "email": "Alice@example.com", "name": "Alice", "company": "Acme",
    }, ctx))
    assert rec.ok, rec.error
    assert rec.result["created"] is True
    assert rec.result["email"] == "alice@example.com"


def test_crm_advance_stage_returns_updated_false_when_missing():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    ctx.sql.query = AsyncMock(return_value=[])  # type: ignore[method-assign]
    rec = asyncio.run(reg.call("crm_advance_stage", {
        "email": "missing@x.com", "new_stage": "contacted",
    }, ctx))
    assert rec.ok, rec.error
    assert rec.result["updated"] is False


def test_lead_score_writes_score_to_db():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    ctx.llm.complete = AsyncMock(return_value='{"score": 78, "rationale": "B2B fit"}')
    ctx.sql.query = AsyncMock(return_value=[])  # type: ignore[method-assign]
    rec = asyncio.run(reg.call("lead_score", {
        "email": "Sue@b.com", "title": "VP Sales", "company": "B",
    }, ctx))
    assert rec.ok, rec.error
    assert rec.result["score"] == 78.0
    ctx.sql.query.assert_called_once()


def test_email_warmup_inbox_clean_publishes_intent():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="cmo", budget_usd=0)
    ctx.bus.publish = AsyncMock(return_value="id-1")  # type: ignore[method-assign]
    rec = asyncio.run(reg.call("email_warmup_inbox_clean", {}, ctx))
    assert rec.ok, rec.error
    topic, payload = ctx.bus.publish.call_args.args
    assert topic == "email.warmup_clean_request"
    assert payload["requested_by"] == "cmo"


def test_hunter_no_creds_returns_no_creds():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    rec = asyncio.run(reg.call("hunter_find_email", {
        "domain": "x.com", "first_name": "A", "last_name": "B",
    }, ctx))
    assert rec.ok, rec.error
    assert rec.result["verification"] == "no_creds"
