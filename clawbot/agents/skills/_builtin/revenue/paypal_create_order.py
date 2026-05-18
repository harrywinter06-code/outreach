META = {
    "name": "paypal_create_order", "builtin": True,
    "description": "Create a PayPal checkout order in GBP. Returns order id + approve_url for the buyer.",
    "params": {"amount_gbp": "float", "return_url": "str", "cancel_url": "str"},
    "returns": {"id": "str", "status": "str", "approve_url": "str"},
    "requires_approval": True,
}


async def run(ctx, amount_gbp: float, return_url: str, cancel_url: str) -> dict:
    result = await ctx.revenue.paypal_create_order(
        amount_gbp=amount_gbp, return_url=return_url, cancel_url=cancel_url,
    )
    return {
        "id": str(result.get("id", "")),
        "status": str(result.get("status", "")),
        "approve_url": str(result.get("approve_url", "")),
    }
