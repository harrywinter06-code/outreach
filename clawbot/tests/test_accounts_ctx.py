"""AccountsClient protocol — noop behavior, SkillCtx wiring."""
import asyncio


def test_noop_accounts_create_returns_stub():
    from clawbot.skill_ctx import make_noop_ctx
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    result = asyncio.run(ctx.accounts.create_account(
        service="substack", signup_url="https://substack.com/signup",
    ))
    assert result["status"] == "noop"
    assert result["service"] == "substack"


def test_noop_accounts_get_returns_none():
    from clawbot.skill_ctx import make_noop_ctx
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    result = asyncio.run(ctx.accounts.get_account(service="substack", email="x@y.com"))
    assert result is None


def test_noop_accounts_list_returns_empty():
    from clawbot.skill_ctx import make_noop_ctx
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    assert asyncio.run(ctx.accounts.list_accounts(status="live")) == []


def test_skill_ctx_has_accounts_field():
    from clawbot.skill_ctx import make_noop_ctx, SkillCtx
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    assert hasattr(ctx, "accounts")
    assert "accounts" in SkillCtx.__dataclass_fields__


def test_shadow_ctx_has_accounts_field():
    from clawbot.shadow_ctx import make_shadow_ctx
    ctx = make_shadow_ctx(caller_id="t", budget_usd=0)
    assert hasattr(ctx, "accounts")
    assert asyncio.run(ctx.accounts.list_accounts(status="live")) == []
