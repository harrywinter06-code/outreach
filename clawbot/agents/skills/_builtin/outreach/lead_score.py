META = {
    "name": "lead_score", "builtin": True,
    "description": "Score a lead 0-100 on fit + intent using ctx.llm. Higher = better. Writes score back to the leads row when present.",
    "params": {
        "email": "str", "name": "str", "title": "str",
        "company": "str", "intent_signal": "str",
    },
    "returns": {"score": "float", "rationale": "str"},
    "cost_estimate_usd": 0.003,
}


async def run(
    ctx, email: str, name: str = "", title: str = "",
    company: str = "", intent_signal: str = "",
) -> dict:
    import json as _json
    import re as _re
    prompt = (
        "Score this lead from 0-100 for fit+intent to a B2B SaaS sale. "
        "Higher score = better. Output JSON only: "
        "{\"score\":0-100, \"rationale\":\"≤30 words\"}.\n\n"
        f"Email: {email}\nName: {name}\nTitle: {title}\n"
        f"Company: {company}\nIntent signal: {intent_signal}"
    )
    text = await ctx.llm.complete(
        system="You are a precise lead-qualification engine. Output only JSON.",
        user=prompt, tier="worker",
    )
    m = _re.search(r"\{.*\}", text, _re.DOTALL)
    score = 0.0
    rationale = ""
    if m:
        try:
            d = _json.loads(m.group(0))
            score = float(d.get("score", 0) or 0)
            rationale = str(d.get("rationale", ""))
        except _json.JSONDecodeError:
            pass
    norm = email.strip().lower()
    if norm:
        try:
            await ctx.sql.query(
                "UPDATE leads SET score = $1, updated_at = NOW() WHERE email = $2",
                score, norm,
            )
        except Exception:
            pass
    return {"score": score, "rationale": rationale}
