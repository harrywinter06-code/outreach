META = {
    "name": "secret_get", "builtin": True,
    "description": "Read an allowlisted secret. Throws if not allowlisted — never enumerate.",
    "params": {"name": "str"},
    "returns": {"value": "str"},
}


async def run(ctx, name: str) -> dict:
    return {"value": ctx.secret.get(name)}
