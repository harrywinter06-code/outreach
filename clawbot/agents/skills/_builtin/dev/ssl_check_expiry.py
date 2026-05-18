META = {
    "name": "ssl_check_expiry", "builtin": True,
    "description": "Fetch the SSL certificate expiry date for a hostname via the public "
                   "ssl-checker.io API (no auth). Returns ISO date of expiry plus days remaining.",
    "params": {"host": "str"},
    "returns": {"expires_at_iso": "str", "days_remaining": "int", "issuer": "str"},
    "cost_estimate_usd": 0.0, "timeout_s": 20.0,
}


async def run(ctx, host: str) -> dict:
    import json as _json
    from datetime import datetime as _dt
    resp = await ctx.http.get(f"https://ssl-checker.io/api/v1/check/{host}")
    try:
        data = _json.loads(resp.get("text") or "{}")
    except ValueError:
        data = {}
    result = data.get("result") if isinstance(data.get("result"), dict) else data
    expires_iso = (result or {}).get("valid_till") or (result or {}).get("not_after") or ""
    issuer = (result or {}).get("issued_by") or (result or {}).get("issuer") or ""
    days_remaining = 0
    if expires_iso:
        try:
            expires_dt = _dt.fromisoformat(expires_iso.replace("Z", "+00:00"))
            now_iso = ctx.time.now_iso()
            now_dt = _dt.fromisoformat(now_iso.replace("Z", "+00:00"))
            days_remaining = max(0, (expires_dt - now_dt).days)
        except ValueError:
            days_remaining = 0
    return {
        "expires_at_iso": expires_iso,
        "days_remaining": days_remaining,
        "issuer": str(issuer) if not isinstance(issuer, str) else issuer,
    }
