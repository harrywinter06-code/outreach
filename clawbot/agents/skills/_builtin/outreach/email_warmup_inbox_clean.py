META = {
    "name": "email_warmup_inbox_clean", "builtin": True,
    "description": "Queue an IMAP inbox cleanup pass for warmup replies. Publishes intent to the bus; a worker performs the IMAP read+move.",
    "params": {},
    "returns": {"ok": "bool", "request_id": "str"},
}


async def run(ctx) -> dict:
    import uuid as _uuid
    request_id = _uuid.uuid4().hex
    msg_id = await ctx.bus.publish("email.warmup_clean_request", {
        "request_id": request_id,
        "requested_by": ctx.caller_id,
        "requested_at_iso": ctx.time.now_iso(),
    })
    return {"ok": bool(msg_id), "request_id": request_id}
