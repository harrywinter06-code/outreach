META = {
    "name": "linkedin_post", "builtin": True,
    "description": "Post a share update on LinkedIn. Returns the post id.",
    "params": {"text": "str"},
    "returns": {"id": "str"},
}


async def run(ctx, text: str) -> dict:
    return await ctx.social.linkedin_post(text=text)
