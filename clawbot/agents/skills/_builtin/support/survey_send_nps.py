META = {
    "name": "survey_send_nps", "builtin": True,
    "description": "Send an NPS survey email with an embedded scoring link. "
                   "The link encodes customer_id so replies are attributable.",
    "params": {"to": "str", "customer_id": "str", "survey_url": "str"},
    "returns": {"id": "str", "ok": "bool"},
    "cost_estimate_usd": 0.0, "timeout_s": 20.0,
}


async def run(ctx, to: str, customer_id: str, survey_url: str) -> dict:
    link = f"{survey_url}?cid={customer_id}"
    body_text = (
        "Thanks for using our product. On a scale of 0 to 10, how likely are you to "
        f"recommend us to a friend?\n\nScore here: {link}\n\n"
        "One reply takes 10 seconds and helps us improve."
    )
    body_html = (
        f"<p>Thanks for using our product.</p>"
        f"<p>On a scale of 0 to 10, how likely are you to recommend us to a friend?</p>"
        f"<p><a href=\"{link}\">Click to score</a> — 10 seconds.</p>"
    )
    result = await ctx.email.send(
        to=to, subject="Quick question (10 seconds)",
        body_text=body_text, body_html=body_html,
    )
    return {"id": result.get("id", ""), "ok": bool(result.get("id"))}
