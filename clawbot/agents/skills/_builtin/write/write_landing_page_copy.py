META = {
    "name": "write_landing_page_copy", "builtin": True,
    "description": "Generate landing-page copy: headline, subhead, 3-5 bullets, CTA.",
    "params": {"product_name": "str", "value_prop": "str", "audience": "str"},
    "returns": {"headline": "str", "subhead": "str", "bullets": "list", "cta": "str"},
    "cost_estimate_usd": 0.01,
}


async def run(ctx, product_name: str, value_prop: str, audience: str) -> dict:
    import json as _json
    import re as _re
    system = (
        "You write landing-page copy that converts. Output JSON: "
        "{\"headline\": str (≤12 words, benefit-led), "
        "\"subhead\": str (≤25 words, who+what+why), "
        "\"bullets\": [str, ...] (3-5 items, ≤15 words each, concrete outcomes), "
        "\"cta\": str (≤6 words, imperative verb)}. "
        "No marketing-speak. No vague claims."
    )
    user = (
        f"Product: {product_name}\n"
        f"Value prop: {value_prop}\n"
        f"Audience: {audience}\n\n"
        f"Output JSON only."
    )
    text = await ctx.llm.complete(system=system, user=user, tier="worker")
    m = _re.search(r"\{.*\}", text, _re.DOTALL)
    if m:
        try:
            d = _json.loads(m.group(0))
            bullets = d.get("bullets", [])
            if not isinstance(bullets, list):
                bullets = [str(bullets)]
            return {
                "headline": str(d.get("headline", "")),
                "subhead": str(d.get("subhead", "")),
                "bullets": [str(b) for b in bullets],
                "cta": str(d.get("cta", "")),
            }
        except _json.JSONDecodeError:
            pass
    return {"headline": product_name, "subhead": value_prop, "bullets": [], "cta": "Get started"}
