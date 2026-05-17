META = {
    "name": "email_send", "builtin": True,
    "description": "Send an email via Resend. Returns the message id.",
    "params": {"to": "str", "subject": "str", "body_text": "str", "body_html": "str", "reply_to": "str"},
    "returns": {"id": "str"},
}


async def run(ctx, to: str, subject: str, body_text: str, body_html: str = "", reply_to: str = "") -> dict:
    return await ctx.email.send(
        to=to,
        subject=subject,
        body_text=body_text,
        body_html=body_html or None,
        reply_to=reply_to or None,
    )
