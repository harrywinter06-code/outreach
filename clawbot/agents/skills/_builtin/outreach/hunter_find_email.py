META = {
    "name": "hunter_find_email", "builtin": True,
    "description": "Find a professional email via Hunter.io email finder. Requires HUNTER_API_KEY.",
    "params": {"domain": "str", "first_name": "str", "last_name": "str"},
    "returns": {"email": "str", "score": "float", "verification": "str"},
}


async def run(ctx, domain: str, first_name: str, last_name: str) -> dict:
    import json as _json
    key = ctx.secret.get("HUNTER_API_KEY")
    if not key:
        return {"email": "", "score": 0.0, "verification": "no_creds"}
    url = (
        "https://api.hunter.io/v2/email-finder"
        f"?domain={domain}&first_name={first_name}&last_name={last_name}&api_key={key}"
    )
    res = await ctx.http.get(url)
    try:
        body = _json.loads(res.get("text", "{}")).get("data", {})
    except _json.JSONDecodeError:
        body = {}
    return {
        "email": str(body.get("email", "")),
        "score": float(body.get("score", 0) or 0) / 100.0,
        "verification": str(body.get("verification", {}).get("status", "")),
    }
