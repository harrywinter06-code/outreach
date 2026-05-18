META = {
    "name": "domain_register", "builtin": True,
    "description": "Register a domain via Cloudflare Registrar. Operator-gated — every call "
                   "requires Telegram approval before the registration fee is committed. "
                   "Needs CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID.",
    "params": {"domain": "str", "years": "int", "auto_renew": "bool"},
    "returns": {"registered": "bool", "domain": "str", "price_usd": "float"},
    "cost_estimate_usd": 10.0, "timeout_s": 60.0, "requires_approval": True,
}


async def run(ctx, domain: str, years: int = 1, auto_renew: bool = True) -> dict:
    import json as _json
    token = ctx.secret.get("CLOUDFLARE_API_TOKEN")
    account_id = ctx.secret.get("CLOUDFLARE_ACCOUNT_ID")
    payload = {
        "name": domain,
        "auto_renew": auto_renew,
        "period": years,
    }
    resp = await ctx.http.post(
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}/registrar/domains",
        json=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        data = _json.loads(resp.get("text") or "{}")
    except ValueError:
        data = {}
    success = bool(data.get("success"))
    result = data.get("result") or {}
    price = result.get("registration_fee_amount") or 0.0
    return {
        "registered": success,
        "domain": domain,
        "price_usd": float(price or 0.0),
    }
