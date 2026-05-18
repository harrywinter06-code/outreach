import re

META = {
    "name": "arxiv_search", "builtin": True,
    "description": "Search arXiv via its public API. Returns paper id/title/summary/authors.",
    "params": {"query": "str", "max_results": "int"},
    "returns": {"papers": "list", "status": "int"},
    "cost_estimate_usd": 0.0, "timeout_s": 30.0,
}


async def run(ctx, query: str, max_results: int = 10) -> dict:
    encoded = query.replace(" ", "+")
    resp = await ctx.http.get(
        f"http://export.arxiv.org/api/query?search_query=all:{encoded}"
        f"&start=0&max_results={max_results}",
    )
    text = str(resp.get("text", ""))
    papers: list[dict] = []
    for entry in re.findall(r"<entry>(.*?)</entry>", text, flags=re.DOTALL):
        def _grab(tag: str) -> str:
            m = re.search(rf"<{tag}>(.*?)</{tag}>", entry, flags=re.DOTALL)
            return m.group(1).strip() if m else ""
        authors = re.findall(r"<name>(.*?)</name>", entry)
        papers.append({
            "id": _grab("id"),
            "title": re.sub(r"\s+", " ", _grab("title")),
            "summary": re.sub(r"\s+", " ", _grab("summary"))[:1000],
            "authors": authors,
            "published": _grab("published"),
        })
    return {"papers": papers, "status": int(resp.get("status", 0))}
