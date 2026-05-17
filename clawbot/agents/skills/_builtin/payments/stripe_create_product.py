META = {
    "name": "stripe_create_product", "builtin": True,
    "description": "Create a Stripe product. Returns the product id for use in create_price.",
    "params": {"name": "str", "description": "str"},
    "returns": {"id": "str", "name": "str"},
}


async def run(ctx, name: str, description: str) -> dict:
    return await ctx.payments.create_product(name=name, description=description)
