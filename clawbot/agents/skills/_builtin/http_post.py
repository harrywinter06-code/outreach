META = {
    "name": "http_post", "builtin": True,
    "description": "HTTP POST with JSON body. Returns status and text.",
    "params": {"url": "str", "json": "dict", "headers": "dict"},
    "returns": {"status": "int", "text": "str"},
}


async def run(ctx, url: str, json: dict | None = None, headers: dict | None = None) -> dict:
    return await ctx.http.post(url, json=json, headers=headers)
