META = {
    "name": "write_cold_email", "builtin": True,
    "description": "Write a cold outreach email. Returns subject + body_text. Short, specific, one ask.",
    "params": {"recipient_name": "str", "recipient_company": "str", "offer": "str", "evidence": "str"},
    "returns": {"subject": "str", "body_text": "str"},
    "cost_estimate_usd": 0.01,
}


async def run(ctx, recipient_name: str, recipient_company: str, offer: str, evidence: str = "") -> dict:
    import json as _json
    import re as _re
    system = (
        "You write cold emails that get replies. ≤120 words total body. "
        "Structure: 1) one-line context showing you researched them, "
        "2) the offer in one sentence, 3) one specific ask (yes/no question). "
        "No 'hope this finds you well'. No follow-up promises. "
        "Output JSON: {\"subject\": str, \"body_text\": str}."
    )
    user = (
        f"Recipient: {recipient_name} at {recipient_company}\n"
        f"Offer: {offer}\n"
        f"Research/evidence about them: {evidence or 'none provided'}\n\n"
        f"Write the email as JSON."
    )
    text = await ctx.llm.complete(system=system, user=user, tier="worker")
    m = _re.search(r"\{.*\}", text, _re.DOTALL)
    if m:
        try:
            d = _json.loads(m.group(0))
            return {"subject": str(d.get("subject", "")), "body_text": str(d.get("body_text", ""))}
        except _json.JSONDecodeError:
            pass
    return {"subject": f"Quick question about {recipient_company}", "body_text": text.strip()}
