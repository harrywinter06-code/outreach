META = {
    "name": "stripe_list_authorizations", "builtin": True,
    "description": "List recent card-spend authorizations. Returns count and the list. "
                   "Use to audit what an agent actually spent money on.",
    "params": {"card_id": "str", "limit": "int"},
    "returns": {"count": "int", "authorizations": "list"},
    "cost_estimate_usd": 0.0, "timeout_s": 10.0,
}


async def run(ctx, card_id: str, limit: int = 20) -> dict:
    auths = await ctx.payments.list_authorizations(card_id=card_id, limit=limit)
    return {"count": len(auths), "authorizations": auths}
