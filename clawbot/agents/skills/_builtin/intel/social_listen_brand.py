META = {
    "name": "social_listen_brand", "builtin": True,
    "description": "Aggregate brand mentions across X, Reddit, and HN via ctx.search. Returns deduped hit list.",
    "params": {"brand": "str", "max_per_source": "int"},
    "returns": {"mentions": "list", "source_counts": "dict"},
    "cost_estimate_usd": 0.003, "timeout_s": 60.0,
}


async def run(ctx, brand: str, max_per_source: int = 10) -> dict:
    sources = {
        "x": f'"{brand}" site:twitter.com OR site:x.com',
        "reddit": f'"{brand}" site:reddit.com',
        "hn": f'"{brand}" site:news.ycombinator.com',
    }
    mentions: list[dict] = []
    counts: dict[str, int] = {}
    for label, query in sources.items():
        hits = await ctx.search.search(query, max_results=max_per_source)
        counts[label] = len(hits)
        for h in hits:
            if not isinstance(h, dict):
                continue
            mentions.append({
                "source": label,
                "url": h.get("url", ""),
                "title": h.get("title", ""),
            })
    seen: set[str] = set()
    deduped: list[dict] = []
    for m in mentions:
        if m["url"] and m["url"] not in seen:
            seen.add(m["url"])
            deduped.append(m)
    return {"mentions": deduped, "source_counts": counts}
