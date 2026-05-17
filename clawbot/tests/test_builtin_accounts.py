"""Builtin account-management skills route through ctx.accounts.*"""
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


def test_account_create_skill_routes_to_ctx():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="cmo", budget_usd=0.10)
    ctx.accounts.create_account = AsyncMock(return_value={
        "status": "live", "service": "substack",
        "email": "substack-1@example.com", "url": "https://substack.com/signup",
    })
    record = asyncio.run(reg.call("account_create", {
        "service": "substack", "signup_url": "https://substack.com/signup",
    }, ctx))
    assert record.ok is True
    assert record.result["status"] == "live"
    ctx.accounts.create_account.assert_called_once()


def test_account_get_skill_returns_creds_when_present():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="cmo", budget_usd=0.10)
    ctx.accounts.get_account = AsyncMock(return_value={
        "service": "s", "email": "e@x.com", "password": "p",
        "cookies_json": "{}", "status": "live",
        "last_login_iso": "2026-01-01T00:00:00+00:00", "notes": "",
    })
    record = asyncio.run(reg.call("account_get", {
        "service": "s", "email": "e@x.com",
    }, ctx))
    assert record.ok is True
    assert record.result["password"] == "p"


def test_account_get_skill_returns_not_found_dict_for_missing():
    """Skill returns dict with 'found': False rather than None — registry rejects None."""
    reg = _registry()
    ctx = make_noop_ctx(caller_id="cmo", budget_usd=0.10)
    ctx.accounts.get_account = AsyncMock(return_value=None)
    record = asyncio.run(reg.call("account_get", {
        "service": "missing", "email": "no@x.com",
    }, ctx))
    assert record.ok is True
    assert record.result["found"] is False


def test_account_list_skill_returns_count_and_items():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="cmo", budget_usd=0.10)
    ctx.accounts.list_accounts = AsyncMock(return_value=[
        {"service": "a", "email": "a@x.com", "password": "p1",
         "cookies_json": "", "status": "live",
         "last_login_iso": "x", "notes": ""},
    ])
    record = asyncio.run(reg.call("account_list", {"status": "live"}, ctx))
    assert record.ok is True
    assert record.result["count"] == 1
    assert len(record.result["accounts"]) == 1


def test_account_mark_zombie_skill_passes_reason():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="cmo", budget_usd=0.10)
    ctx.accounts.mark_zombie = AsyncMock(return_value={
        "service": "x", "email": "e@x.com", "status": "zombie", "reason": "stuck",
    })
    record = asyncio.run(reg.call("account_mark_zombie", {
        "service": "x", "email": "e@x.com", "reason": "stuck",
    }, ctx))
    assert record.ok is True
    assert record.result["status"] == "zombie"
