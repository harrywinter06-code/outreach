META = {
    "name": "directory_submit_g2", "builtin": True,
    "description": "Submit a new software product to G2 (https://sell.g2.com/get-listed). "
                   "Browser-driven; expects vendor account session. Returns vendor portal URL.",
    "params": {
        "product_name": "str", "company_name": "str", "website": "str",
        "category": "str", "description": "str", "contact_email": "str",
    },
    "returns": {"listing_url": "str", "success": "bool"},
    "cost_estimate_usd": 0.0, "timeout_s": 240.0,
}


async def run(
    ctx, product_name: str, company_name: str, website: str,
    category: str, description: str, contact_email: str,
) -> dict:
    task = (
        f"Go to https://sell.g2.com/get-listed. "
        f"Fill the 'Get Listed' form: product name {product_name!r}, "
        f"company name {company_name!r}, website {website}, "
        f"primary category {category!r}, product description {description!r}, "
        f"contact email {contact_email}. "
        f"Submit. Return the resulting vendor-portal URL or confirmation page."
    )
    result = await ctx.browser.run(task=task, max_steps=30)
    return {
        "listing_url": result.get("output", ""),
        "success": bool(result.get("success")),
    }
