META = {
    "name": "tone_rewrite", "builtin": True,
    "description": "Rewrite text in a target tone (e.g., 'casual', 'formal', 'direct', 'enthusiastic').",
    "params": {"text": "str", "target_tone": "str"},
    "returns": {"text": "str"},
    "cost_estimate_usd": 0.005,
}


async def run(ctx, text: str, target_tone: str) -> dict:
    system = (
        "You rewrite text in a target tone while preserving meaning and facts. "
        "Do not add or remove information. Output the rewritten text only — "
        "no preamble, no explanation."
    )
    user = (
        f"Target tone: {target_tone}\n\n"
        f"Original:\n{text[:8000]}"
    )
    out = await ctx.llm.complete(system=system, user=user, tier="worker")
    return {"text": out.strip()}
