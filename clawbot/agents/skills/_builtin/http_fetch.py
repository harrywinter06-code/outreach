META = {
    "name": "http_fetch", "builtin": True,
    "description": "HTTP GET. Returns sanitized text and status. Use for any external read.",
    "params": {"url": "str", "headers": "dict"},
    "returns": {"status": "int", "text": "str", "headers": "dict"},
    "cost_estimate_usd": 0.0, "timeout_s": 30.0,
}


async def run(ctx, url: str, headers: dict | None = None) -> dict:
    response = await ctx.http.get(url, headers=headers)
    return response
