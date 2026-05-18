META = {
    "name": "pypi_publish", "builtin": True,
    "description": "Build a Python wheel in cwd and upload to PyPI via twine. Needs "
                   "TWINE_USERNAME / TWINE_PASSWORD (or TWINE_API_KEY) in the runner env. "
                   "Two-step via ctx.dev allowlist: pip_wheel then twine_upload.",
    "params": {"cwd": "str"},
    "returns": {
        "build_returncode": "int", "upload_returncode": "int",
        "build_stderr": "str", "upload_stderr": "str",
    },
    "cost_estimate_usd": 0.0, "timeout_s": 600.0,
}


async def run(ctx, cwd: str) -> dict:
    build = await ctx.dev.exec_allowed_command(
        cmd_name="pip_wheel", args=[], cwd=cwd,
    )
    if int(build.get("returncode", 1)) != 0:
        return {
            "build_returncode": int(build.get("returncode", 1)),
            "upload_returncode": -1,
            "build_stderr": build.get("stderr", ""),
            "upload_stderr": "",
        }
    upload = await ctx.dev.exec_allowed_command(
        cmd_name="twine_upload", args=[], cwd=cwd,
    )
    return {
        "build_returncode": int(build.get("returncode", 0)),
        "upload_returncode": int(upload.get("returncode", 1)),
        "build_stderr": build.get("stderr", ""),
        "upload_stderr": upload.get("stderr", ""),
    }
