META = {
    "name": "web_deep_research", "builtin": True,
    "description": "Multi-source research on a topic: web search + extract top result + LLM synthesis. Returns a short cited summary.",
    "params": {"topic": "str", "max_results": "int"},
    "returns": {"summary": "str", "sources": "list"},
    "cost_estimate_usd": 0.01, "timeout_s": 180.0,
}


async def run(ctx, topic: str, max_results: int = 5) -> dict:
    hits = await ctx.search.search(topic, max_results=max_results)
    sources = []
    snippets: list[str] = []
    for h in hits[:max_results]:
        url = h.get("url", "") if isinstance(h, dict) else ""
        title = h.get("title", "") if isinstance(h, dict) else ""
        snippet = h.get("content") or h.get("snippet") or "" if isinstance(h, dict) else ""
        sources.append({"url": url, "title": title})
        if snippet:
            snippets.append(f"[{title}]({url})\n{snippet}")

    if not snippets:
        return {"summary": "", "sources": sources}

    user = (
        f"Research topic: {topic}\n\n"
        f"Source snippets:\n\n" + "\n\n---\n\n".join(snippets) + "\n\n"
        f"Write a 3-5 sentence synthesis. Cite each source as [n]."
    )
    summary = await ctx.llm.complete(
        system="You are a research analyst. Cite sources [1], [2], etc. Be terse.",
        user=user,
        tier="executive",
    )
    return {"summary": summary, "sources": sources}
