META = {
    "name": "cloudflare_purge_cache", "builtin": True,
    "description": "Purge specific URLs from Cloudflare's edge cache for a zone. "
                   "Needs CLOUDFLARE_API_TOKEN. Pass [] to purge everything (use with care).",
    "params": {"zone_id": "str", "urls": "list"},
    "returns": {"success": "bool", "purged": "int"},
    "cost_estimate_usd": 0.0, "timeout_s": 20.0,
}


async def run(ctx, zone_id: str, urls: list | None = None) -> dict:
    import json as _json
    token = ctx.secret.get("CLOUDFLARE_API_TOKEN")
    urls = urls or []
    payload: dict = {"files": urls} if urls else {"purge_everything": True}
    resp = await ctx.http.post(
        f"https://api.cloudflare.com/client/v4/zones/{zone_id}/purge_cache",
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
    return {
        "success": bool(data.get("success", False)),
        "purged": len(urls),
    }
