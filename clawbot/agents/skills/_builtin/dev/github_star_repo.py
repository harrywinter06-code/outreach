META = {
    "name": "github_star_repo", "builtin": True,
    "description": "Star a public GitHub repo as the authenticated user. Cheap reputation builder "
                   "for projects we depend on or want to surface. Needs GITHUB_TOKEN.",
    "params": {"owner": "str", "repo": "str"},
    "returns": {"starred": "bool", "status": "int"},
    "cost_estimate_usd": 0.0, "timeout_s": 10.0,
}


async def run(ctx, owner: str, repo: str) -> dict:
    token = ctx.secret.get("GITHUB_TOKEN")
    resp = await ctx.http.post(
        f"https://api.github.com/user/starred/{owner}/{repo}",
        json={},
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Length": "0",
        },
    )
    status = int(resp.get("status", 0))
    return {"starred": status in (204, 304), "status": status}
