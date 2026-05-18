META = {
    "name": "hn_show_submit", "builtin": True,
    "description": "Submit a 'Show HN' post to Hacker News (https://news.ycombinator.com/submit). "
                   "Requires a stored HN session. Title must start with 'Show HN:'. Returns post URL.",
    "params": {"title": "str", "url": "str", "text": "str"},
    "returns": {"post_url": "str", "success": "bool"},
    "cost_estimate_usd": 0.0, "timeout_s": 120.0,
}


async def run(ctx, title: str, url: str = "", text: str = "") -> dict:
    final_title = title if title.lower().startswith("show hn:") else f"Show HN: {title}"
    body_clause = (
        f"Fill the URL field with {url}. Leave text empty."
        if url else
        f"Leave URL empty. Paste the following into the text field:\n\n{text[:4000]}"
    )
    task = (
        f"Go to https://news.ycombinator.com/submit. "
        f"Set the title to {final_title!r}. "
        f"{body_clause}\n\n"
        f"Click Submit. Return the resulting post URL (e.g. .../item?id=N)."
    )
    result = await ctx.browser.run(task=task, max_steps=20)
    return {
        "post_url": result.get("output", ""),
        "success": bool(result.get("success")),
    }
