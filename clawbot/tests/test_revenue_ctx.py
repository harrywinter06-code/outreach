"""RevenueClient protocol — noop behaviour + SkillCtx + shadow_ctx wiring."""
import asyncio


def test_noop_revenue_gumroad_methods_return_stub():
    from clawbot.skill_ctx import make_noop_ctx
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    assert asyncio.run(ctx.revenue.gumroad_list_products()) == []
    assert asyncio.run(ctx.revenue.gumroad_sales_last_7d_gbp()) == 0.0
    assert asyncio.run(ctx.revenue.gumroad_sales_today_gbp()) == 0.0
    sale = asyncio.run(ctx.revenue.gumroad_get_sale(sale_id="abc"))
    assert sale["sale_id"] == "abc"
    assert sale["found"] is False


def test_noop_revenue_paypal_methods_return_stub():
    from clawbot.skill_ctx import make_noop_ctx
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    order = asyncio.run(ctx.revenue.paypal_create_order(
        amount_gbp=10.0, return_url="https://r", cancel_url="https://c",
    ))
    assert "id" in order and order["amount_gbp"] == 10.0
    capture = asyncio.run(ctx.revenue.paypal_capture_order(order_id="x"))
    assert capture["id"] == "x"
    txns = asyncio.run(ctx.revenue.paypal_list_transactions(
        start_date="2026-01-01T00:00:00-0000", end_date="2026-01-02T00:00:00-0000",
    ))
    assert txns == []
    assert asyncio.run(ctx.revenue.paypal_today_gbp()) == 0.0


def test_noop_revenue_crypto_methods_return_stub():
    from clawbot.skill_ctx import make_noop_ctx
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    charge = asyncio.run(ctx.revenue.crypto_generate_receive_address(
        amount_gbp=50.0, description="payment",
    ))
    assert charge["currency"] == "BTC"
    bal = asyncio.run(ctx.revenue.crypto_check_balance(charge_id="abc"))
    assert bal["charge_id"] == "abc"


def test_noop_revenue_subscription_methods_return_stub():
    from clawbot.skill_ctx import make_noop_ctx
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    sub = asyncio.run(ctx.revenue.subscription_create(
        customer_id="cus_x", price_id="price_y",
    ))
    assert sub["customer"] == "cus_x"
    cancel = asyncio.run(ctx.revenue.subscription_cancel(subscription_id="sub_x"))
    assert cancel["id"] == "sub_x"
    assert cancel["status"] == "canceled"


def test_skill_ctx_has_revenue_field():
    from clawbot.skill_ctx import make_noop_ctx, SkillCtx
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    assert hasattr(ctx, "revenue")
    assert "revenue" in SkillCtx.__dataclass_fields__


def test_shadow_ctx_has_revenue_field():
    from clawbot.shadow_ctx import make_shadow_ctx
    ctx = make_shadow_ctx(caller_id="t", budget_usd=0)
    assert hasattr(ctx, "revenue")
    assert asyncio.run(ctx.revenue.gumroad_list_products()) == []


def test_live_revenue_gracefully_no_ops_without_keys():
    """Without any creds, _LiveRevenue methods should return zero/empty without raising."""
    from clawbot.skill_ctx import _LiveRevenue
    live = _LiveRevenue()
    assert asyncio.run(live.gumroad_list_products()) == []
    assert asyncio.run(live.gumroad_sales_last_7d_gbp()) == 0.0
    order = asyncio.run(live.paypal_create_order(
        amount_gbp=10.0, return_url="https://r", cancel_url="https://c",
    ))
    assert order["status"] == "no_creds"
    charge = asyncio.run(live.crypto_generate_receive_address(
        amount_gbp=1.0, description="x",
    ))
    assert charge["address"] == ""
    sub = asyncio.run(live.subscription_create(customer_id="x", price_id="y"))
    assert sub["status"] == "no_creds"
