META = {
    "name": "gumroad_list_products", "builtin": True,
    "description": "List all Gumroad products visible to this account. Returns list of products with id/name/price_gbp.",
    "params": {},
    "returns": {"products": "list", "count": "int"},
}


async def run(ctx) -> dict:
    products = await ctx.revenue.gumroad_list_products()
    return {"products": products, "count": len(products)}
