META = {
    "name": "github_create_release", "builtin": True,
    "description": "Create a release on a GitHub repo (owner/name) tagged at tag_name. "
                   "Needs GITHUB_TOKEN.",
    "params": {
        "owner": "str", "repo": "str", "tag_name": "str",
        "name": "str", "body": "str", "draft": "bool",
    },
    "returns": {"id": "str", "html_url": "str"},
    "cost_estimate_usd": 0.0, "timeout_s": 20.0,
}


async def run(
    ctx, owner: str, repo: str, tag_name: str,
    name: str = "", body: str = "", draft: bool = False,
) -> dict:
    import json as _json
    token = ctx.secret.get("GITHUB_TOKEN")
    resp = await ctx.http.post(
        f"https://api.github.com/repos/{owner}/{repo}/releases",
        json={
            "tag_name": tag_name, "name": name or tag_name,
            "body": body, "draft": draft,
        },
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
        "id": str(data.get("id", "")),
        "html_url": data.get("html_url", ""),
    }
