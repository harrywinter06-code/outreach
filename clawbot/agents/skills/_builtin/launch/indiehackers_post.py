META = {
    "name": "indiehackers_post", "builtin": True,
    "description": "Post to IndieHackers in a chosen group. Requires a stored IH session "
                   "(account_create + browser_load_session first). Returns post URL.",
    "params": {"group_slug": "str", "title": "str", "body_markdown": "str"},
    "returns": {"post_url": "str", "success": "bool"},
    "cost_estimate_usd": 0.0, "timeout_s": 180.0,
}


async def run(ctx, group_slug: str, title: str, body_markdown: str) -> dict:
    task = (
        f"Go to https://www.indiehackers.com/group/{group_slug}/new-post. "
        f"Set the post title to {title!r}. "
        f"Paste the following markdown into the body editor:\n\n{body_markdown[:8000]}\n\n"
        f"Click Publish. Return the resulting post URL."
    )
    result = await ctx.browser.run(task=task, max_steps=25)
    return {
        "post_url": result.get("output", ""),
        "success": bool(result.get("success")),
    }
