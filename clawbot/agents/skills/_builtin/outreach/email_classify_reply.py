META = {
    "name": "email_classify_reply", "builtin": True,
    "description": "Classify a reply email into: positive | negative | ooo | unsubscribe | referral | unclear.",
    "params": {"from_addr": "str", "subject": "str", "body": "str"},
    "returns": {"label": "str", "confidence": "float"},
    "cost_estimate_usd": 0.002,
}


async def run(ctx, from_addr: str, subject: str, body: str) -> dict:
    import json as _json
    import re as _re
    prompt = (
        "Classify this email reply into exactly one of: positive, negative, "
        "ooo, unsubscribe, referral, unclear. Output JSON only: "
        "{\"label\":..., \"confidence\":0-1}.\n\n"
        f"From: {from_addr}\nSubject: {subject}\nBody:\n{body[:2000]}"
    )
    text = await ctx.llm.complete(
        system="You are a precise email classifier. Output only JSON.",
        user=prompt, tier="worker",
    )
    m = _re.search(r"\{.*\}", text, _re.DOTALL)
    if not m:
        return {"label": "unclear", "confidence": 0.0}
    try:
        d = _json.loads(m.group(0))
    except _json.JSONDecodeError:
        return {"label": "unclear", "confidence": 0.0}
    return {
        "label": str(d.get("label", "unclear")),
        "confidence": float(d.get("confidence", 0.0) or 0.0),
    }
