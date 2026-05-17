META = {
    "name": "reddit_comment", "builtin": True,
    "description": "Reply to a Reddit post or comment. parent_id must include prefix e.g. t3_ for posts.",
    "params": {"parent_id": "str", "body": "str"},
    "returns": {"id": "str"},
}


async def run(ctx, parent_id: str, body: str) -> dict:
    return await ctx.social.reddit_comment(parent_id=parent_id, body=body)
