import datetime
import json

META = {
    "name": "github_trending", "builtin": True,
    "description": "GitHub's official Search API doesn't expose 'trending' directly. This skill returns repos created in the last N days, sorted by stars — a stable approximation.",
    "params": {"language": "str", "days": "int", "per_page": "int"},
    "returns": {"repos": "list", "status": "int"},
    "cost_estimate_usd": 0.0, "timeout_s": 30.0,
}


async def run(ctx, language: str = "", days: int = 7, per_page: int = 25) -> dict:
    since = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=days)).date().isoformat()
    q = f"created:>{since}"
    if language:
        q += f" language:{language}"
    q_encoded = q.replace(" ", "+").replace(":", "%3A").replace(">", "%3E")
    resp = await ctx.http.get(
        f"https://api.github.com/search/repositories?q={q_encoded}&sort=stars&order=desc&per_page={per_page}",
        headers={"Accept": "application/vnd.github+json"},
    )
    text = str(resp.get("text", ""))
    repos: list = []
    if resp.get("status") == 200 and text:
        try:
            for item in json.loads(text).get("items", []):
                repos.append({
                    "name": item.get("full_name"),
                    "url": item.get("html_url"),
                    "stars": item.get("stargazers_count"),
                    "description": item.get("description"),
                    "language": item.get("language"),
                })
        except (ValueError, json.JSONDecodeError):
            repos = []
    return {"repos": repos, "status": int(resp.get("status", 0))}
