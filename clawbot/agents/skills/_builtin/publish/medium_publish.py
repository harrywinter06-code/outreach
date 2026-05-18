META = {
    "name": "medium_publish", "builtin": True,
    "description": "Publish a post to Medium via the Integration API. Requires MEDIUM_INTEGRATION_TOKEN + MEDIUM_USER_ID.",
    "params": {"title": "str", "body_markdown": "str", "tags": "list", "publish_status": "str"},
    "returns": {"ok": "bool", "url": "str", "id": "str"},
}


async def run(
    ctx, title: str, body_markdown: str,
    tags: list | None = None, publish_status: str = "public",
) -> dict:
    import json as _json
    token = ctx.secret.get("MEDIUM_INTEGRATION_TOKEN")
    user_id = ctx.secret.get("MEDIUM_USER_ID")
    if not (token and user_id):
        return {"ok": False, "url": "", "id": ""}
    payload = {
        "title": title,
        "contentFormat": "markdown",
        "content": body_markdown,
        "tags": (tags or [])[:5],
        "publishStatus": publish_status,
    }
    res = await ctx.http.post(
        f"https://api.medium.com/v1/users/{user_id}/posts",
        json=payload,
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json", "Accept": "application/json"},
    )
    ok = 200 <= int(res.get("status", 0)) < 300
    try:
        data = _json.loads(res.get("text", "{}")).get("data", {})
    except _json.JSONDecodeError:
        data = {}
    return {"ok": ok, "url": str(data.get("url", "")), "id": str(data.get("id", ""))}
