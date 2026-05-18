META = {
    "name": "github_create_repo", "builtin": True,
    "description": "Create a new GitHub repo on the authenticated user. Needs GITHUB_TOKEN. "
                   "Returns clone URL and html URL.",
    "params": {"name": "str", "description": "str", "private": "bool"},
    "returns": {"clone_url": "str", "html_url": "str"},
    "cost_estimate_usd": 0.0, "timeout_s": 20.0,
}


async def run(ctx, name: str, description: str = "", private: bool = False) -> dict:
    import json as _json
    token = ctx.secret.get("GITHUB_TOKEN")
    resp = await ctx.http.post(
        "https://api.github.com/user/repos",
        json={"name": name, "description": description, "private": private},
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        data = _json.loads(resp.get("text") or "{}")
    except ValueError:
        data = {}
    return {
        "clone_url": data.get("clone_url", ""),
        "html_url": data.get("html_url", ""),
    }
