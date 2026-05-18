META = {
    "name": "stripe_create_payment_link", "builtin": True,
    "description": "Create a Stripe Payment Link URL. business_id is required so the webhook can attribute payments back to the originating business.",
    "params": {"price_id": "str", "business_id": "str"},
    "returns": {"url": "str", "id": "str"},
}


async def run(ctx, price_id: str, business_id: str) -> dict:
    return await ctx.payments.create_payment_link(
        price_id=price_id, metadata={"business_id": business_id},
    )
