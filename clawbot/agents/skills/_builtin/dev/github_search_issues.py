META = {
    "name": "github_search_issues", "builtin": True,
    "description": "Search GitHub issues across all public repos with the given query string. "
                   "Useful for finding bug-bounty / contribution candidates. Optional GITHUB_TOKEN "
                   "raises rate limit from 10 to 30 requests/minute.",
    "params": {"query": "str", "per_page": "int"},
    "returns": {"items": "list", "total_count": "int"},
    "cost_estimate_usd": 0.0, "timeout_s": 15.0,
}


async def run(ctx, query: str, per_page: int = 30) -> dict:
    import json as _json
    token = ctx.secret.get("GITHUB_TOKEN") if hasattr(ctx, "secret") else ""
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = (
        f"https://api.github.com/search/issues?q={query}"
        f"&per_page={per_page}"
    )
    resp = await ctx.http.get(url, headers=headers)
    try:
        data = _json.loads(resp.get("text") or "{}")
    except ValueError:
        data = {}
    return {
        "items": data.get("items", []),
        "total_count": int(data.get("total_count", 0)),
    }
