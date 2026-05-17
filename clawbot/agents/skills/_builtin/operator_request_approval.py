META = {
    "name": "operator_request_approval", "builtin": True,
    "description": "Block until operator approves/denies via Telegram. Returns False on timeout.",
    "params": {"prompt": "str", "timeout_s": "float"},
    "returns": {"approved": "bool"},
    "timeout_s": 3700.0,
}


async def run(ctx, prompt: str, timeout_s: float = 3600.0) -> dict:
    return {"approved": await ctx.operator.request_approval(prompt, timeout_s=timeout_s)}
