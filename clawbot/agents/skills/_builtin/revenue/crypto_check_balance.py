META = {
    "name": "crypto_check_balance", "builtin": True,
    "description": "Check Coinbase Commerce charge status + paid amount. Returns status (NEW/PENDING/COMPLETED) and GBP amount received.",
    "params": {"charge_id": "str"},
    "returns": {"charge_id": "str", "status": "str", "paid_amount_gbp": "float"},
}


async def run(ctx, charge_id: str) -> dict:
    result = await ctx.revenue.crypto_check_balance(charge_id=charge_id)
    return {
        "charge_id": str(result.get("charge_id", charge_id)),
        "status": str(result.get("status", "")),
        "paid_amount_gbp": float(result.get("paid_amount_gbp", 0.0)),
    }
