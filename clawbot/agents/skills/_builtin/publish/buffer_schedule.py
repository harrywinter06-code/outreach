META = {
    "name": "buffer_schedule", "builtin": True,
    "description": "Schedule a post via Buffer API. Requires BUFFER_ACCESS_TOKEN. profile_ids comma-separated.",
    "params": {"profile_ids": "str", "text": "str", "scheduled_at_iso": "str"},
    "returns": {"ok": "bool", "id": "str"},
}


async def run(
    ctx, profile_ids: str, text: str, scheduled_at_iso: str = "",
) -> dict:
    import json as _json
    from datetime import datetime
    token = ctx.secret.get("BUFFER_ACCESS_TOKEN")
    if not token:
        return {"ok": False, "id": ""}
    payload: dict = {
        "profile_ids[]": [p.strip() for p in profile_ids.split(",") if p.strip()],
        "text": text,
    }
    if scheduled_at_iso:
        try:
            ts = int(datetime.fromisoformat(scheduled_at_iso.replace("Z", "+00:00")).timestamp())
            payload["scheduled_at"] = ts
        except ValueError:
            pass
    res = await ctx.http.post(
        "https://api.bufferapp.com/1/updates/create.json",
        json=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    ok = 200 <= int(res.get("status", 0)) < 300
    try:
        body = _json.loads(res.get("text", "{}"))
        updates = body.get("updates", [])
        post_id = str(updates[0].get("id", "")) if updates else ""
    except _json.JSONDecodeError:
        post_id = ""
    return {"ok": ok, "id": post_id}
