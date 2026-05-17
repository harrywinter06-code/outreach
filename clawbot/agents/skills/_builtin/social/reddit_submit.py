META = {
    "name": "reddit_submit", "builtin": True,
    "description": "Submit a post to a subreddit. Provide body for text posts or url for link posts.",
    "params": {"subreddit": "str", "title": "str", "body": "str", "url": "str"},
    "returns": {"id": "str"},
}


async def run(ctx, subreddit: str, title: str, body: str = "", url: str = "") -> dict:
    return await ctx.social.reddit_submit(
        subreddit=subreddit,
        title=title,
        body=body or None,
        url=url or None,
    )
