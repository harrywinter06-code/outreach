META = {
    "name": "stripe_refund", "builtin": True,
    "description": "Issue a refund on a charge. amount_pence=None means full refund. Use to resolve disputes proactively.",
    "params": {"charge_id": "str", "amount_pence": "int"},
    "returns": {"id": "str"},
    "requires_approval": True,
}


async def run(ctx, charge_id: str, amount_pence: int | None = None) -> dict:
    return await ctx.payments.refund(charge_id=charge_id, amount_pence=amount_pence)
