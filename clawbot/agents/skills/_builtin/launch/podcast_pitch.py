META = {
    "name": "podcast_pitch", "builtin": True,
    "description": "Pitch a podcast guest spot. Looks up the show contact page via HTTP, "
                   "extracts a contact email (if visible) and emails a pitch. If no email "
                   "found, returns ok=False with a hint so the caller can fall back to browser.",
    "params": {
        "show_name": "str", "show_url": "str", "guest_name": "str",
        "guest_bio": "str", "topic": "str",
    },
    "returns": {"id": "str", "ok": "bool", "contact_email": "str"},
    "cost_estimate_usd": 0.0, "timeout_s": 30.0,
}


async def run(
    ctx, show_name: str, show_url: str, guest_name: str,
    guest_bio: str, topic: str,
) -> dict:
    import re as _re
    page = await ctx.http.get(show_url)
    text = page.get("text", "")
    candidates = _re.findall(
        r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", text,
    )
    contact = ""
    for addr in candidates:
        lower = addr.lower()
        if any(noise in lower for noise in ("noreply", "no-reply", "donotreply")):
            continue
        contact = addr
        break
    if not contact:
        return {"id": "", "ok": False, "contact_email": ""}
    subject = f"Guest pitch for {show_name}: {topic}"
    body = (
        f"Hi {show_name} team,\n\n"
        f"I'd love to pitch {guest_name} as a guest on {topic}.\n\n"
        f"Why this fits the show: {guest_bio}\n\n"
        f"Happy to share a one-pager or a 30s intro clip if useful.\n\n"
        f"Best,\n{guest_name}"
    )
    sent = await ctx.email.send(to=contact, subject=subject, body_text=body)
    return {
        "id": sent.get("id", ""),
        "ok": bool(sent.get("id")),
        "contact_email": contact,
    }
