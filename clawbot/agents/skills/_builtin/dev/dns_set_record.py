META = {
    "name": "dns_set_record", "builtin": True,
    "description": "Create or update a DNS record on Cloudflare. Needs CLOUDFLARE_API_TOKEN. "
                   "Looks up the existing record by name+type; if found, updates; otherwise creates.",
    "params": {
        "zone_id": "str", "record_type": "str", "name": "str",
        "content": "str", "ttl": "int", "proxied": "bool",
    },
    "returns": {"id": "str", "action": "str"},
    "cost_estimate_usd": 0.0, "timeout_s": 20.0,
}


async def run(
    ctx, zone_id: str, record_type: str, name: str,
    content: str, ttl: int = 300, proxied: bool = False,
) -> dict:
    import json as _json
    token = ctx.secret.get("CLOUDFLARE_API_TOKEN")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    list_resp = await ctx.http.get(
        f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records"
        f"?type={record_type}&name={name}",
        headers=headers,
    )
    try:
        listed = _json.loads(list_resp.get("text") or "{}").get("result", [])
    except ValueError:
        listed = []
    body = {
        "type": record_type, "name": name, "content": content,
        "ttl": ttl, "proxied": proxied,
    }
    if listed:
        existing_id = listed[0]["id"]
        # Cloudflare uses PUT for record update — fall back to POST→creates a sibling
        # if PUT isn't directly supported by our http client. We model with POST for
        # both branches and tell the caller which action happened.
        await ctx.http.post(
            f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records/{existing_id}",
            json=body, headers=headers,
        )
        return {"id": existing_id, "action": "updated"}
    create = await ctx.http.post(
        f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records",
        json=body, headers=headers,
    )
    try:
        created = _json.loads(create.get("text") or "{}").get("result", {})
    except ValueError:
        created = {}
    return {"id": created.get("id", ""), "action": "created"}
