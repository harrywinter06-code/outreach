META = {
    "name": "stripe_create_payment_link", "builtin": True,
    "description": "Create a permanent Stripe Payment Link URL for a price. Customers can pay without a checkout build.",
    "params": {"price_id": "str"},
    "returns": {"url": "str", "id": "str"},
}


async def run(ctx, price_id: str) -> dict:
    return await ctx.payments.create_payment_link(price_id=price_id)
