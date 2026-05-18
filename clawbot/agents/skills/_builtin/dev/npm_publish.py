META = {
    "name": "npm_publish", "builtin": True,
    "description": "Publish the package in cwd to npm. Requires NPM_TOKEN in the environment "
                   "of the runner. cwd must contain package.json; access controlled by "
                   "ctx.dev allowlist.",
    "params": {"cwd": "str", "extra_args": "list"},
    "returns": {"stdout": "str", "stderr": "str", "returncode": "int"},
    "cost_estimate_usd": 0.0, "timeout_s": 300.0,
}


async def run(ctx, cwd: str, extra_args: list | None = None) -> dict:
    result = await ctx.dev.exec_allowed_command(
        cmd_name="npm_publish",
        args=list(extra_args or []),
        cwd=cwd,
    )
    return {
        "stdout": result.get("stdout", ""),
        "stderr": result.get("stderr", ""),
        "returncode": int(result.get("returncode", 1)),
    }
