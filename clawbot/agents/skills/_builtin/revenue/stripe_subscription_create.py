META = {
    "name": "stripe_subscription_create", "builtin": True,
    "description": "Create a Stripe subscription for a customer at a given price. Returns the subscription id + status.",
    "params": {"customer_id": "str", "price_id": "str"},
    "returns": {"id": "str", "customer": "str", "status": "str"},
    "requires_approval": True,
}


async def run(ctx, customer_id: str, price_id: str) -> dict:
    result = await ctx.revenue.subscription_create(
        customer_id=customer_id, price_id=price_id,
    )
    return {
        "id": str(result.get("id", "")),
        "customer": str(result.get("customer", customer_id)),
        "status": str(result.get("status", "")),
    }
