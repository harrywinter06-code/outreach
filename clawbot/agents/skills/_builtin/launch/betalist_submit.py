META = {
    "name": "betalist_submit", "builtin": True,
    "description": "Submit a startup to BetaList (https://betalist.com/submit). Public form, "
                   "no auth required. Returns the submission URL. 30-90s.",
    "params": {
        "name": "str", "url": "str", "description": "str",
        "category": "str", "contact_email": "str",
    },
    "returns": {"submission_url": "str", "success": "bool"},
    "cost_estimate_usd": 0.0, "timeout_s": 180.0,
}


async def run(
    ctx, name: str, url: str, description: str,
    category: str, contact_email: str,
) -> dict:
    task = (
        f"Go to https://betalist.com/submit. Fill the form: "
        f"startup name {name!r}, website URL {url}, "
        f"description {description!r}, category {category!r}, "
        f"contact email {contact_email}. Submit. "
        f"Return the resulting submission/confirmation page URL."
    )
    result = await ctx.browser.run(task=task, max_steps=25)
    return {
        "submission_url": result.get("output", ""),
        "success": bool(result.get("success")),
    }
