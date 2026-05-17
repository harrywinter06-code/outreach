META = {
    "name": "stripe_freeze_card", "builtin": True,
    "description": "Cancel a Stripe Issuing card permanently. Use for compromised or "
                   "decommissioned agent cards.",
    "params": {"card_id": "str"},
    "returns": {"id": "str", "status": "str"},
    "cost_estimate_usd": 0.0, "timeout_s": 10.0,
}


async def run(ctx, card_id: str) -> dict:
    result = await ctx.payments.freeze_card(card_id=card_id)
    return {"id": result["id"], "status": result["status"]}
