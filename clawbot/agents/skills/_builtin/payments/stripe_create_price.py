META = {
    "name": "stripe_create_price", "builtin": True,
    "description": "Create a Stripe price for an existing product. amount_pence is integer pence (e.g. 900 = £9.00). recurring=True for monthly subscription.",
    "params": {"product_id": "str", "amount_pence": "int", "currency": "str", "recurring": "bool"},
    "returns": {"id": "str"},
}


async def run(ctx, product_id: str, amount_pence: int, currency: str = "gbp", recurring: bool = False) -> dict:
    return await ctx.payments.create_price(
        product_id=product_id, amount_pence=amount_pence, currency=currency, recurring=recurring
    )
