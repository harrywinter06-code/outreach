"""Builtin Stripe Issuing skills."""
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


def test_stripe_issue_card_routes_to_payments():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="cfo", budget_usd=0.10)
    ctx.payments.issue_card = AsyncMock(return_value={
        "id": "ic_abc", "last4": "4242", "exp_month": 12,
        "exp_year": 2028, "status": "active", "cardholder": "ich_x",
    })
    record = asyncio.run(reg.call("stripe_issue_card", {
        "cardholder_id": "ich_x", "daily_limit_usd": 25, "agent_id": "cmo",
    }, ctx))
    assert record.ok is True
    assert record.result["id"] == "ic_abc"
    assert record.result["last4"] == "4242"


def test_stripe_freeze_card_routes_to_payments():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="cfo", budget_usd=0.10)
    ctx.payments.freeze_card = AsyncMock(return_value={
        "id": "ic_x", "status": "canceled",
    })
    record = asyncio.run(reg.call("stripe_freeze_card", {
        "card_id": "ic_x",
    }, ctx))
    assert record.ok is True
    assert record.result["status"] == "canceled"


def test_stripe_list_authorizations_returns_count():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="cfo", budget_usd=0.10)
    ctx.payments.list_authorizations = AsyncMock(return_value=[
        {"id": "iauth_1", "amount": 500, "merchant_data": {"name": "Substack"}},
        {"id": "iauth_2", "amount": 1200, "merchant_data": {"name": "Mailgun"}},
    ])
    record = asyncio.run(reg.call("stripe_list_authorizations", {
        "card_id": "ic_x", "limit": 10,
    }, ctx))
    assert record.ok is True
    assert record.result["count"] == 2
    assert len(record.result["authorizations"]) == 2
