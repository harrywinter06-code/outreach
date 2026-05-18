META = {
    "name": "gumroad_sales_last_7d", "builtin": True,
    "description": "Sum of Gumroad GBP sales over the last 7 days.",
    "params": {},
    "returns": {"total_gbp": "float"},
}


async def run(ctx) -> dict:
    total = await ctx.revenue.gumroad_sales_last_7d_gbp()
    return {"total_gbp": float(total)}
