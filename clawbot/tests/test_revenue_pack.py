"""Revenue skill pack: discovery + smoke calls + aggregate composition."""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

from clawbot.skill_registry import SkillRegistry
from clawbot.skill_ctx import make_noop_ctx

REVENUE_DIR = Path(__file__).parent.parent / "agents" / "skills" / "_builtin" / "revenue"


def _registry() -> SkillRegistry:
    reg = SkillRegistry(skills_dir=REVENUE_DIR)
    reg.discover()
    return reg


def test_revenue_pack_loads():
    reg = _registry()
    names = set(reg.list_names())
    expected = {
        "gumroad_list_products", "gumroad_sales_last_7d", "gumroad_get_sale",
        "paypal_create_order", "paypal_capture_order", "paypal_list_transactions",
        "crypto_generate_receive_address", "crypto_check_balance",
        "stripe_subscription_create", "stripe_subscription_cancel",
        "revenue_aggregate_today_gbp",
    }
    missing = expected - names
    assert not missing, f"missing revenue skills: {missing}"


def test_revenue_aggregate_runs_noop():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    rec = asyncio.run(reg.call("revenue_aggregate_today_gbp", {}, ctx))
    assert rec.ok, rec.error
    assert "total_gbp" in rec.result
    assert "by_provider" in rec.result
    assert rec.result["total_gbp"] == 0.0


def test_revenue_aggregate_sums_providers():
    """Aggregate should compose ctx.payments + ctx.revenue.gumroad + paypal."""
    from datetime import datetime, UTC
    reg = _registry()
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    today_epoch = datetime.now(UTC).timestamp()
    ctx.payments.list_charges = AsyncMock(return_value=[
        {"amount": 1500, "currency": "gbp", "created": today_epoch},  # £15
        {"amount": 9999, "currency": "usd", "created": today_epoch},  # ignored
    ])
    ctx.revenue.gumroad_sales_today_gbp = AsyncMock(return_value=7.50)
    ctx.revenue.paypal_today_gbp = AsyncMock(return_value=3.20)
    rec = asyncio.run(reg.call("revenue_aggregate_today_gbp", {}, ctx))
    assert rec.ok, rec.error
    assert rec.result["total_gbp"] == 25.70
    assert rec.result["by_provider"]["stripe"] == 15.0
    assert rec.result["by_provider"]["gumroad"] == 7.50
    assert rec.result["by_provider"]["paypal"] == 3.20


def test_gumroad_list_products_routes_to_revenue():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    ctx.revenue.gumroad_list_products = AsyncMock(return_value=[
        {"id": "p1", "name": "Book", "price_gbp": 9.99, "url": "", "currency": "gbp"},
    ])
    rec = asyncio.run(reg.call("gumroad_list_products", {}, ctx))
    assert rec.ok, rec.error
    assert rec.result["count"] == 1


def test_paypal_create_order_routes_to_revenue():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    ctx.revenue.paypal_create_order = AsyncMock(return_value={
        "id": "ORDER_123", "status": "CREATED", "approve_url": "https://paypal/approve",
        "amount_gbp": 50.0,
    })
    rec = asyncio.run(reg.call("paypal_create_order", {
        "amount_gbp": 50.0,
        "return_url": "https://x/ok", "cancel_url": "https://x/no",
    }, ctx))
    assert rec.ok, rec.error
    assert rec.result["id"] == "ORDER_123"
    assert rec.result["approve_url"] == "https://paypal/approve"


def test_crypto_generate_receive_address_routes():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    ctx.revenue.crypto_generate_receive_address = AsyncMock(return_value={
        "charge_id": "CC123", "address": "bc1qabc", "currency": "BTC",
        "amount_gbp": 100.0, "hosted_url": "https://commerce.coinbase.com/c/CC123",
    })
    rec = asyncio.run(reg.call("crypto_generate_receive_address", {
        "amount_gbp": 100.0, "description": "test charge",
    }, ctx))
    assert rec.ok, rec.error
    assert rec.result["address"] == "bc1qabc"
    assert rec.result["charge_id"] == "CC123"


def test_stripe_subscription_create_routes():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    ctx.revenue.subscription_create = AsyncMock(return_value={
        "id": "sub_abc", "customer": "cus_x", "status": "active", "price_id": "price_y",
    })
    rec = asyncio.run(reg.call("stripe_subscription_create", {
        "customer_id": "cus_x", "price_id": "price_y",
    }, ctx))
    assert rec.ok, rec.error
    assert rec.result["id"] == "sub_abc"
    assert rec.result["status"] == "active"
