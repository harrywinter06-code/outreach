META = {
    "name": "revenue_aggregate_today_gbp", "builtin": True,
    "description": "Sum today's GBP revenue across Stripe + Gumroad + PayPal. Returns total + per-provider breakdown.",
    "params": {},
    "returns": {"total_gbp": "float", "by_provider": "dict"},
}


async def run(ctx) -> dict:
    from datetime import datetime, UTC
    today = datetime.now(UTC).date()
    stripe_charges = await ctx.payments.list_charges(limit=100)
    stripe_today_gbp = 0.0
    for c in stripe_charges:
        if c.get("currency") != "gbp":
            continue
        created = c.get("created", 0)
        try:
            d = datetime.fromtimestamp(float(created), UTC).date()
        except (TypeError, ValueError, OSError):
            continue
        if d == today:
            stripe_today_gbp += float(c.get("amount", 0)) / 100.0
    gumroad_gbp = await ctx.revenue.gumroad_sales_today_gbp()
    paypal_gbp = await ctx.revenue.paypal_today_gbp()
    total = round(stripe_today_gbp + gumroad_gbp + paypal_gbp, 2)
    return {
        "total_gbp": total,
        "by_provider": {
            "stripe": round(stripe_today_gbp, 2),
            "gumroad": round(gumroad_gbp, 2),
            "paypal": round(paypal_gbp, 2),
        },
    }
