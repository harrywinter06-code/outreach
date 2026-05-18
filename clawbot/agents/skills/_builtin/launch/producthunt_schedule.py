META = {
    "name": "producthunt_schedule", "builtin": True,
    "description": "Schedule a Product Hunt launch via browser auth. Requires a stored PH session "
                   "(use account_create then browser_load_session). Returns launch_url. 90-180s.",
    "params": {
        "name": "str", "tagline": "str", "description": "str",
        "url": "str", "scheduled_for_iso": "str", "thumbnail_url": "str",
    },
    "returns": {"launch_url": "str", "success": "bool"},
    "cost_estimate_usd": 0.0, "timeout_s": 300.0,
}


async def run(
    ctx, name: str, tagline: str, description: str, url: str,
    scheduled_for_iso: str, thumbnail_url: str = "",
) -> dict:
    task = (
        f"Go to https://www.producthunt.com/posts/new. "
        f"Fill the product fields — name: {name!r}, tagline: {tagline!r}, "
        f"description: {description!r}, product URL: {url}. "
        f"If a thumbnail field exists, upload from {thumbnail_url or '(skip)'}. "
        f"Set scheduled launch date to {scheduled_for_iso}. "
        f"Submit. Return the resulting launch page URL."
    )
    result = await ctx.browser.run(task=task, max_steps=40)
    return {
        "launch_url": result.get("output", ""),
        "success": bool(result.get("success")),
    }
