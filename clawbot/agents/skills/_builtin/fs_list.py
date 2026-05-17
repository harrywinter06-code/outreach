META = {
    "name": "fs_list", "builtin": True,
    "description": "List directory contents under sandboxed roots.",
    "params": {"path": "str"},
    "returns": {"entries": "list"},
}


async def run(ctx, path: str) -> dict:
    return {"entries": await ctx.fs.list(path)}
