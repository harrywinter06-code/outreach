META = {
    "name": "dev_to_publish", "builtin": True,
    "description": "Publish an article to dev.to via the Forem API. Requires DEVTO_API_KEY.",
    "params": {"title": "str", "body_markdown": "str", "tags": "list", "published": "bool"},
    "returns": {"ok": "bool", "url": "str", "id": "str"},
}


async def run(
    ctx, title: str, body_markdown: str,
    tags: list | None = None, published: bool = True,
) -> dict:
    import json as _json
    api_key = ctx.secret.get("DEVTO_API_KEY")
    if not api_key:
        return {"ok": False, "url": "", "id": ""}
    payload = {"article": {
        "title": title,
        "body_markdown": body_markdown,
        "published": bool(published),
        "tags": (tags or [])[:4],
    }}
    res = await ctx.http.post(
        "https://dev.to/api/articles",
        json=payload,
        headers={"api-key": api_key, "Content-Type": "application/json",
                 "Accept": "application/vnd.forem.api-v1+json"},
    )
    ok = 200 <= int(res.get("status", 0)) < 300
    try:
        data = _json.loads(res.get("text", "{}"))
    except _json.JSONDecodeError:
        data = {}
    return {
        "ok": ok,
        "url": str(data.get("url", "")),
        "id": str(data.get("id", "")),
    }
