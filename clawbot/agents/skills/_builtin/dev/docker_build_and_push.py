META = {
    "name": "docker_build_and_push", "builtin": True,
    "description": "Build a Docker image in cwd and push to a registry. Composes docker_build, "
                   "docker_tag, and docker_push via ctx.dev. The runner must already be docker-login'd "
                   "to the target registry (DOCKERHUB_USERNAME / DOCKERHUB_TOKEN handled at "
                   "the runner level).",
    "params": {"cwd": "str", "image": "str", "tag": "str"},
    "returns": {"image_ref": "str", "returncode": "int", "stderr": "str"},
    "cost_estimate_usd": 0.0, "timeout_s": 1200.0,
}


async def run(ctx, cwd: str, image: str, tag: str = "latest") -> dict:
    ref = f"{image}:{tag}"
    build = await ctx.dev.exec_allowed_command(
        cmd_name="docker_build",
        args=["-t", ref, "."],
        cwd=cwd,
    )
    if int(build.get("returncode", 1)) != 0:
        return {"image_ref": ref, "returncode": int(build.get("returncode", 1)),
                "stderr": build.get("stderr", "")}
    push = await ctx.dev.exec_allowed_command(
        cmd_name="docker_push", args=[ref], cwd=cwd,
    )
    return {
        "image_ref": ref,
        "returncode": int(push.get("returncode", 1)),
        "stderr": push.get("stderr", ""),
    }
