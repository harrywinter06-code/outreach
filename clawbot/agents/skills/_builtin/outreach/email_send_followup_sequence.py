META = {
    "name": "email_send_followup_sequence", "builtin": True,
    "description": "Queue a multi-day followup sequence to a lead. Publishes intent to the bus; a scheduler worker fires the followups.",
    "params": {
        "lead_email": "str", "sequence_id": "str",
        "days_between": "int", "max_followups": "int",
    },
    "returns": {"ok": "bool", "request_id": "str"},
    "requires_approval": True,
}


async def run(
    ctx, lead_email: str, sequence_id: str,
    days_between: int = 3, max_followups: int = 3,
) -> dict:
    import uuid as _uuid
    request_id = _uuid.uuid4().hex
    msg_id = await ctx.bus.publish("email.followup_sequence_request", {
        "request_id": request_id,
        "lead_email": lead_email,
        "sequence_id": sequence_id,
        "days_between": max(1, int(days_between)),
        "max_followups": max(1, min(10, int(max_followups))),
        "requested_by": ctx.caller_id,
        "requested_at_iso": ctx.time.now_iso(),
    })
    return {"ok": bool(msg_id), "request_id": request_id}
