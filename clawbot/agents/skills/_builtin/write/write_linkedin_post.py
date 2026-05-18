META = {
    "name": "write_linkedin_post", "builtin": True,
    "description": "Write a LinkedIn post (~1300 chars). Hook first line, short paragraphs, no emojis unless requested.",
    "params": {"topic": "str", "audience": "str", "tone": "str"},
    "returns": {"text": "str"},
    "cost_estimate_usd": 0.01,
}


async def run(ctx, topic: str, audience: str, tone: str = "professional") -> dict:
    system = (
        "You write LinkedIn posts that get read. Open with a sharp first line. "
        "Use 1-2 sentence paragraphs separated by blank lines. ≤1300 chars total. "
        "No emojis unless asked. Plain text, no markdown."
    )
    user = (
        f"Topic: {topic}\n"
        f"Audience: {audience}\n"
        f"Tone: {tone}\n\n"
        f"Write the post. Plain text only, no preamble."
    )
    text = await ctx.llm.complete(system=system, user=user, tier="worker")
    return {"text": text[:1300]}
