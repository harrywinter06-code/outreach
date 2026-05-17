META = {
    "name": "llm_complete", "builtin": True,
    "description": "Single-turn LLM completion. tier='executive' for harder reasoning, 'worker' for fast.",
    "params": {"system": "str", "user": "str", "tier": "str"},
    "returns": {"text": "str"},
    "cost_estimate_usd": 0.002,
}


async def run(ctx, system: str, user: str, tier: str = "worker") -> dict:
    text = await ctx.llm.complete(system=system, user=user, tier=tier)
    return {"text": text}
