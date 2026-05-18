META = {
    "name": "translate", "builtin": True,
    "description": "Translate text between languages. Pass ISO codes (e.g., 'en', 'es', 'fr').",
    "params": {"text": "str", "source_lang": "str", "target_lang": "str"},
    "returns": {"text": "str"},
    "cost_estimate_usd": 0.003,
}


async def run(ctx, text: str, source_lang: str, target_lang: str) -> dict:
    system = (
        "You translate text precisely. Preserve meaning, register, and formatting. "
        "Output the translation only — no commentary, no quotation marks, no "
        "language labels."
    )
    user = (
        f"Translate from {source_lang} to {target_lang}:\n\n{text[:8000]}"
    )
    out = await ctx.llm.complete(system=system, user=user, tier="worker")
    return {"text": out.strip()}
