META = {
    "name": "gumroad_get_sale", "builtin": True,
    "description": "Look up a single Gumroad sale by id. Returns sale details + found flag.",
    "params": {"sale_id": "str"},
    "returns": {"sale_id": "str", "found": "bool", "price_gbp": "float", "email": "str"},
}


async def run(ctx, sale_id: str) -> dict:
    result = await ctx.revenue.gumroad_get_sale(sale_id=sale_id)
    return {
        "sale_id": result.get("sale_id", sale_id),
        "found": bool(result.get("found", False)),
        "price_gbp": float(result.get("price_gbp", 0.0)),
        "email": str(result.get("email", "")),
    }
