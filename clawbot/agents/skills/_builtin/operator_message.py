META = {
    "name": "operator_message", "builtin": True,
    "description": "Send a message to the human operator via Telegram + bus. level: info, warn, urgent.",
    "params": {"text": "str", "level": "str"},
    "returns": {"sent": "bool"},
}


async def run(ctx, text: str, level: str = "info") -> dict:
    await ctx.operator.message(text, level=level)
    return {"sent": True}
