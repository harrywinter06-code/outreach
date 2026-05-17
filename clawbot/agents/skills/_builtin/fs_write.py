META = {
    "name": "fs_write", "builtin": True,
    "description": "Write a file under sandboxed roots. Creates parent dirs. Overwrites.",
    "params": {"path": "str", "content": "str"},
    "returns": {"path": "str"},
}


async def run(ctx, path: str, content: str) -> dict:
    await ctx.fs.write(path, content)
    return {"path": path}
