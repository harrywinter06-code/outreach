META = {
    "name": "email_send_cold", "builtin": True,
    "description": "Send a cold email with deliverability best-practice headers. Checks suppression table first; refuses to send if listed.",
    "params": {
        "to": "str", "subject": "str", "body_text": "str",
        "body_html": "str", "unsubscribe_url": "str",
    },
    "returns": {"ok": "bool", "id": "str", "suppressed": "bool"},
    "requires_approval": True,
}


async def run(
    ctx, to: str, subject: str, body_text: str,
    body_html: str = "", unsubscribe_url: str = "",
) -> dict:
    rows = await ctx.sql.query(
        "SELECT email FROM suppression WHERE email = $1", to,
    )
    if rows:
        return {"ok": False, "id": "", "suppressed": True}
    unsubscribe_line = (
        f"\n\nUnsubscribe: {unsubscribe_url}" if unsubscribe_url else ""
    )
    final_text = body_text + unsubscribe_line
    result = await ctx.email.send(
        to=to, subject=subject,
        body_text=final_text,
        body_html=body_html or None,
    )
    return {
        "ok": bool(result.get("ok", True)),
        "id": str(result.get("id", "")),
        "suppressed": False,
    }
