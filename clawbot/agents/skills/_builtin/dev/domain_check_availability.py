META = {
    "name": "domain_check_availability", "builtin": True,
    "description": "Check if a domain is available for registration via Cloudflare Registrar API. "
                   "Needs CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID. Returns price in USD if available.",
    "params": {"domain": "str"},
    "returns": {"available": "bool", "price_usd": "float", "currency": "str"},
    "cost_estimate_usd": 0.0, "timeout_s": 15.0,
}


async def run(ctx, domain: str) -> dict:
    import json as _json
    token = ctx.secret.get("CLOUDFLARE_API_TOKEN")
    account_id = ctx.secret.get("CLOUDFLARE_ACCOUNT_ID")
    resp = await ctx.http.get(
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}/registrar/domains/{domain}",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        data = _json.loads(resp.get("text") or "{}")
    except ValueError:
        data = {}
    result = data.get("result") or {}
    available = bool(result.get("available", False))
    price = result.get("current_registration_price") or result.get("registration_fee_amount") or 0.0
    return {
        "available": available,
        "price_usd": float(price or 0.0),
        "currency": result.get("currency", "USD"),
    }
