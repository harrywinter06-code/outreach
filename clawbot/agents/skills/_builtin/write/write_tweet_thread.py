META = {
    "name": "write_tweet_thread", "builtin": True,
    "description": "Write a numbered tweet thread (1/N format). Each tweet under 280 chars.",
    "params": {"topic": "str", "n_tweets": "int", "angle": "str"},
    "returns": {"tweets": "list", "count": "int"},
    "cost_estimate_usd": 0.01,
}


async def run(ctx, topic: str, n_tweets: int = 5, angle: str = "") -> dict:
    import re as _re
    n = max(1, min(10, int(n_tweets)))
    system = (
        "You write tweet threads. Each tweet ≤280 chars. No hashtags unless "
        "essential. Open with a hook, close with a takeaway. Output exactly "
        "the requested number of tweets, each prefixed with N/M on its own line."
    )
    user = (
        f"Topic: {topic}\n"
        f"Angle: {angle or 'practical and concrete'}\n"
        f"Number of tweets: {n}\n\n"
        f"Write the thread. Format each as:\n1/{n} <tweet text>\n2/{n} <tweet text>\n..."
    )
    text = await ctx.llm.complete(system=system, user=user, tier="worker")
    tweets: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        m = _re.match(r"^\d+\s*/\s*\d+\s*[:\.\-]?\s*(.+)$", s)
        if m:
            tweets.append(m.group(1)[:280])
    if not tweets and text.strip():
        tweets = [text.strip()[:280]]
    return {"tweets": tweets, "count": len(tweets)}
