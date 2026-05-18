META = {
    "name": "support_send_email_reply", "builtin": True,
    "description": "Send a customer-support email reply with proper reply-to chain. "
                   "Pass the original message-id as reply_to so threading is preserved.",
    "params": {"to": "str", "subject": "str", "body_text": "str", "reply_to": "str"},
    "returns": {"id": "str", "ok": "bool"},
    "cost_estimate_usd": 0.0, "timeout_s": 20.0,
}


async def run(ctx, to: str, subject: str, body_text: str, reply_to: str = "") -> dict:
    result = await ctx.email.send(
        to=to, subject=subject, body_text=body_text,
        reply_to=reply_to or None,
    )
    return {"id": result.get("id", ""), "ok": bool(result.get("id"))}
