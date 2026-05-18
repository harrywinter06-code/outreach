META = {
    "name": "grammar_check", "builtin": True,
    "description": "Correct grammar, spelling, and punctuation. Returns corrected text.",
    "params": {"text": "str"},
    "returns": {"text": "str", "changed": "bool"},
    "cost_estimate_usd": 0.003,
}


async def run(ctx, text: str) -> dict:
    system = (
        "You correct grammar, spelling, and punctuation. Preserve voice, "
        "meaning, and formatting. Output the corrected text only — no "
        "commentary, no diff."
    )
    user = text[:8000]
    out = await ctx.llm.complete(system=system, user=user, tier="worker")
    corrected = out.strip()
    return {"text": corrected, "changed": corrected != text.strip()}
