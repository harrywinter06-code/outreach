META = {
    "name": "paypal_capture_order", "builtin": True,
    "description": "Capture a previously-approved PayPal order. Returns final status + captured amount in GBP.",
    "params": {"order_id": "str"},
    "returns": {"id": "str", "status": "str", "amount_gbp": "float"},
    "requires_approval": True,
}


async def run(ctx, order_id: str) -> dict:
    result = await ctx.revenue.paypal_capture_order(order_id=order_id)
    return {
        "id": str(result.get("id", order_id)),
        "status": str(result.get("status", "")),
        "amount_gbp": float(result.get("amount_gbp", 0.0)),
    }
