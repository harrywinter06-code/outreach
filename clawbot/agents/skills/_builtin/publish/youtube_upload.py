META = {
    "name": "youtube_upload", "builtin": True,
    "description": "Queue a YouTube video upload by publishing an intent to the bus. A worker picks it up; this skill returns the request id, not the final video URL.",
    "params": {"title": "str", "description": "str", "video_path": "str", "tags": "list", "privacy_status": "str"},
    "returns": {"ok": "bool", "request_id": "str"},
    "requires_approval": True,
}


async def run(
    ctx, title: str, description: str, video_path: str,
    tags: list | None = None, privacy_status: str = "private",
) -> dict:
    import uuid as _uuid
    request_id = _uuid.uuid4().hex
    msg_id = await ctx.bus.publish("media.youtube_upload_request", {
        "request_id": request_id,
        "title": title,
        "description": description,
        "video_path": video_path,
        "tags": (tags or [])[:10],
        "privacy_status": privacy_status,
        "requested_by": ctx.caller_id,
        "requested_at_iso": ctx.time.now_iso(),
    })
    return {"ok": bool(msg_id), "request_id": request_id}
