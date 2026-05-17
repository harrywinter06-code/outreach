META = {
    "name": "x_post", "builtin": True,
    "description": "Post a tweet on X (Twitter). Returns the tweet id.",
    "params": {"text": "str", "reply_to": "str"},
    "returns": {"id": "str"},
}


async def run(ctx, text: str, reply_to: str = "") -> dict:
    return await ctx.social.x_post(text=text, reply_to=reply_to or None)
