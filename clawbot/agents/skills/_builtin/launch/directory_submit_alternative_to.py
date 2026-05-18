META = {
    "name": "directory_submit_alternative_to", "builtin": True,
    "description": "Submit a new app listing to AlternativeTo "
                   "(https://alternativeto.net/software/new). Browser-driven. Returns listing URL.",
    "params": {
        "name": "str", "url": "str", "description": "str",
        "category": "str", "alternative_to": "str",
    },
    "returns": {"listing_url": "str", "success": "bool"},
    "cost_estimate_usd": 0.0, "timeout_s": 180.0,
}


async def run(
    ctx, name: str, url: str, description: str,
    category: str, alternative_to: str,
) -> dict:
    task = (
        f"Go to https://alternativeto.net/software/new. "
        f"Fill the new-app form: name {name!r}, official URL {url}, "
        f"description {description!r}, category {category!r}. "
        f"In the 'Alternative To' section, add {alternative_to!r}. "
        f"Submit. Return the resulting listing URL."
    )
    result = await ctx.browser.run(task=task, max_steps=25)
    return {
        "listing_url": result.get("output", ""),
        "success": bool(result.get("success")),
    }
