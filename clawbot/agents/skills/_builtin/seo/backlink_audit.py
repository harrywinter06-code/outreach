import json

META = {
    "name": "backlink_audit", "builtin": True,
    "description": "Pull top backlinks for a target URL via Ahrefs API. Requires AHREFS_API_TOKEN.",
    "params": {"target": "str", "limit": "int", "mode": "str"},
    "returns": {"backlinks": "list", "status": "int"},
    "cost_estimate_usd": 0.01, "timeout_s": 30.0,
}


async def run(ctx, target: str, limit: int = 50, mode: str = "domain") -> dict:
    token = ctx.secret.get("AHREFS_API_TOKEN")
    if not token:
        return {"backlinks": [], "status": 401}
    encoded_target = target.replace(":", "%3A").replace("/", "%2F")
    resp = await ctx.http.get(
        f"https://api.ahrefs.com/v3/site-explorer/all-backlinks?target={encoded_target}"
        f"&mode={mode}&limit={limit}&order_by=domain_rating_source:desc",
        headers={"Authorization": f"Bearer {token}"},
    )
    text = str(resp.get("text", ""))
    backlinks: list = []
    if resp.get("status") == 200 and text:
        try:
            backlinks = json.loads(text).get("backlinks", [])
        except (ValueError, json.JSONDecodeError):
            backlinks = []
    return {"backlinks": backlinks, "status": int(resp.get("status", 0))}
