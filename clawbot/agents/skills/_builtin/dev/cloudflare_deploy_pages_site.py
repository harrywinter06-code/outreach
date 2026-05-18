META = {
    "name": "cloudflare_deploy_pages_site", "builtin": True,
    "description": "Trigger a Cloudflare Pages deploy by pushing the configured branch to its "
                   "git remote (git_push via ctx.dev), then optionally polls the deployment status. "
                   "Pages re-builds automatically from the new commit.",
    "params": {
        "cwd": "str", "branch": "str",
        "project_name": "str", "wait_for_status": "bool",
    },
    "returns": {
        "push_returncode": "int", "deployment_status": "str", "deployment_url": "str",
    },
    "cost_estimate_usd": 0.0, "timeout_s": 600.0,
}


async def run(
    ctx, cwd: str, branch: str = "main",
    project_name: str = "", wait_for_status: bool = False,
) -> dict:
    push = await ctx.dev.exec_allowed_command(
        cmd_name="git_push", args=[branch], cwd=cwd,
    )
    push_rc = int(push.get("returncode", 1))
    if push_rc != 0 or not wait_for_status or not project_name:
        return {
            "push_returncode": push_rc,
            "deployment_status": "pushed" if push_rc == 0 else "push_failed",
            "deployment_url": "",
        }

    import json as _json
    token = ctx.secret.get("CLOUDFLARE_API_TOKEN")
    account_id = ctx.secret.get("CLOUDFLARE_ACCOUNT_ID")
    resp = await ctx.http.get(
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}"
        f"/pages/projects/{project_name}/deployments",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        data = _json.loads(resp.get("text") or "{}")
    except ValueError:
        data = {}
    deployments = data.get("result") or []
    latest = deployments[0] if deployments else {}
    return {
        "push_returncode": push_rc,
        "deployment_status": (latest.get("latest_stage") or {}).get("status", "unknown"),
        "deployment_url": latest.get("url", ""),
    }
