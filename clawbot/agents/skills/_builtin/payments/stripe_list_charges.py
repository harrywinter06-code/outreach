META = {
    "name": "stripe_list_charges", "builtin": True,
    "description": "List recent Stripe charges. Use to read revenue without scraping the dashboard.",
    "params": {"limit": "int"},
    "returns": {"charges": "list"},
}


async def run(ctx, limit: int = 20) -> dict:
    return {"charges": await ctx.payments.list_charges(limit=limit)}
