META = {
    "name": "bluesky_post", "builtin": True,
    "description": "Post to Bluesky via the AT Protocol. Requires BSKY_HANDLE + BSKY_APP_PASSWORD. Text only, ≤300 chars.",
    "params": {"text": "str"},
    "returns": {"ok": "bool", "uri": "str", "cid": "str"},
}


async def run(ctx, text: str) -> dict:
    import json as _json
    from datetime import datetime, UTC
    handle = ctx.secret.get("BSKY_HANDLE")
    password = ctx.secret.get("BSKY_APP_PASSWORD")
    if not (handle and password):
        return {"ok": False, "uri": "", "cid": ""}
    auth = await ctx.http.post(
        "https://bsky.social/xrpc/com.atproto.server.createSession",
        json={"identifier": handle, "password": password},
        headers={"Content-Type": "application/json"},
    )
    if int(auth.get("status", 0)) >= 300:
        return {"ok": False, "uri": "", "cid": ""}
    try:
        sess = _json.loads(auth.get("text", "{}"))
    except _json.JSONDecodeError:
        return {"ok": False, "uri": "", "cid": ""}
    jwt = sess.get("accessJwt", "")
    did = sess.get("did", "")
    if not jwt:
        return {"ok": False, "uri": "", "cid": ""}
    record = {
        "$type": "app.bsky.feed.post",
        "text": text[:300],
        "createdAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    res = await ctx.http.post(
        "https://bsky.social/xrpc/com.atproto.repo.createRecord",
        json={"repo": did, "collection": "app.bsky.feed.post", "record": record},
        headers={"Authorization": f"Bearer {jwt}", "Content-Type": "application/json"},
    )
    ok = 200 <= int(res.get("status", 0)) < 300
    try:
        body = _json.loads(res.get("text", "{}"))
    except _json.JSONDecodeError:
        body = {}
    return {"ok": ok, "uri": str(body.get("uri", "")), "cid": str(body.get("cid", ""))}
