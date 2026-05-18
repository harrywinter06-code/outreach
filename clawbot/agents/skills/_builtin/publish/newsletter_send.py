META = {
    "name": "newsletter_send", "builtin": True,
    "description": "Send a newsletter to subscribers listed in data/subscribers.csv (one email per line). Returns send counts.",
    "params": {"subject": "str", "body_text": "str", "body_html": "str"},
    "returns": {"sent": "int", "failed": "int", "total": "int"},
    "timeout_s": 120.0,
    "requires_approval": True,
}


async def run(
    ctx, subject: str, body_text: str, body_html: str = "",
) -> dict:
    import re as _re
    csv_path = "data/subscribers.csv"
    try:
        raw = await ctx.fs.read(csv_path)
    except Exception:
        raw = ""
    candidates = [line.strip().split(",")[0] for line in raw.splitlines() if line.strip()]
    addresses = [a for a in candidates if _re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", a)]
    sent = 0
    failed = 0
    for addr in addresses:
        try:
            await ctx.email.send(
                to=addr, subject=subject,
                body_text=body_text, body_html=body_html or None,
            )
            sent += 1
        except Exception:
            failed += 1
    return {"sent": sent, "failed": failed, "total": len(addresses)}
