META = {
    "name": "crypto_generate_receive_address", "builtin": True,
    "description": "Generate a crypto receive address via Coinbase Commerce. Creates a fixed-price charge and returns the BTC address + hosted checkout URL.",
    "params": {"amount_gbp": "float", "description": "str"},
    "returns": {"charge_id": "str", "address": "str", "currency": "str", "hosted_url": "str"},
}


async def run(ctx, amount_gbp: float, description: str) -> dict:
    result = await ctx.revenue.crypto_generate_receive_address(
        amount_gbp=amount_gbp, description=description,
    )
    return {
        "charge_id": str(result.get("charge_id", "")),
        "address": str(result.get("address", "")),
        "currency": str(result.get("currency", "BTC")),
        "hosted_url": str(result.get("hosted_url", "")),
    }
