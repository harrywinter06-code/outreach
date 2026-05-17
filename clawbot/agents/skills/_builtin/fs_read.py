META = {
    "name": "fs_read", "builtin": True,
    "description": "Read a file under sandboxed roots (workspace, agents/skills, agents/workers, data).",
    "params": {"path": "str"},
    "returns": {"content": "str"},
}


async def run(ctx, path: str) -> dict:
    return {"content": await ctx.fs.read(path)}
