META = {
    "name": "summarize", "builtin": True,
    "description": "Summarize text into a short bullet list. Returns list of bullets.",
    "params": {"text": "str", "max_bullets": "int"},
    "returns": {"bullets": "list", "count": "int"},
    "cost_estimate_usd": 0.003,
}


async def run(ctx, text: str, max_bullets: int = 5) -> dict:
    import re as _re
    n = max(1, min(15, int(max_bullets)))
    system = (
        "You summarize text into bullet points. Each bullet a complete sentence "
        "≤25 words. Capture distinct facts; don't repeat. Output one bullet per "
        "line, prefixed with '- '."
    )
    user = f"Summarize the following in at most {n} bullets:\n\n{text[:12000]}"
    out = await ctx.llm.complete(system=system, user=user, tier="worker")
    bullets: list[str] = []
    for line in out.splitlines():
        s = line.strip()
        m = _re.match(r"^[-*•]\s+(.+)$", s)
        if m:
            bullets.append(m.group(1))
    return {"bullets": bullets[:n], "count": min(len(bullets), n)}
