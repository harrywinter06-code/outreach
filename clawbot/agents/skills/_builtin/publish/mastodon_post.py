META = {
    "name": "mastodon_post", "builtin": True,
    "description": "Post a status to Mastodon. Requires MASTODON_INSTANCE (e.g., mastodon.social) + MASTODON_ACCESS_TOKEN.",
    "params": {"text": "str", "visibility": "str"},
    "returns": {"ok": "bool", "url": "str", "id": "str"},
}


async def run(ctx, text: str, visibility: str = "public") -> dict:
    import json as _json
    instance = ctx.secret.get("MASTODON_INSTANCE")
    token = ctx.secret.get("MASTODON_ACCESS_TOKEN")
    if not (instance and token):
        return {"ok": False, "url": "", "id": ""}
    instance = instance.strip().rstrip("/")
    if not instance.startswith("http"):
        instance = f"https://{instance}"
    res = await ctx.http.post(
        f"{instance}/api/v1/statuses",
        json={"status": text[:500], "visibility": visibility},
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    ok = 200 <= int(res.get("status", 0)) < 300
    try:
        body = _json.loads(res.get("text", "{}"))
    except _json.JSONDecodeError:
        body = {}
    return {"ok": ok, "url": str(body.get("url", "")), "id": str(body.get("id", ""))}
