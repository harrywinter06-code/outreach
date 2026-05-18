META = {
    "name": "write_long_form_article", "builtin": True,
    "description": "Write a 600-1200 word article on a topic for a target audience. Returns markdown body.",
    "params": {"title": "str", "audience": "str", "key_points": "str"},
    "returns": {"text": "str"},
    "cost_estimate_usd": 0.05,
    "timeout_s": 90.0,
}


async def run(ctx, title: str, audience: str, key_points: str) -> dict:
    system = (
        "You write clear, direct long-form articles. Markdown output. "
        "600-1200 words. Use headings, short paragraphs, concrete examples. "
        "No filler, no marketing-speak."
    )
    user = (
        f"Title: {title}\n"
        f"Audience: {audience}\n"
        f"Key points to cover:\n{key_points}\n\n"
        f"Write the article. Markdown only, no preamble."
    )
    text = await ctx.llm.complete(system=system, user=user, tier="executive")
    return {"text": text}
