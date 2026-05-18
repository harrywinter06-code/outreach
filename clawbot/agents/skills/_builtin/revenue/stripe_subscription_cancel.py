META = {
    "name": "stripe_subscription_cancel", "builtin": True,
    "description": "Cancel an active Stripe subscription. Returns the canceled subscription id + status.",
    "params": {"subscription_id": "str"},
    "returns": {"id": "str", "status": "str"},
    "requires_approval": True,
}


async def run(ctx, subscription_id: str) -> dict:
    result = await ctx.revenue.subscription_cancel(subscription_id=subscription_id)
    return {
        "id": str(result.get("id", subscription_id)),
        "status": str(result.get("status", "")),
    }
