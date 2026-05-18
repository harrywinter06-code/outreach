META = {
    "name": "directory_submit_capterra", "builtin": True,
    "description": "Submit a new software product to Capterra "
                   "(https://www.capterra.com/vendors/sign-up). Browser-driven. Returns vendor URL.",
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
        f"Go to https://www.capterra.com/vendors/sign-up. "
        f"Complete the vendor sign-up form for product {product_name!r} by "
        f"company {company_name!r}, website {website}, "
        f"primary category {category!r}, short description {description!r}, "
        f"contact email {contact_email}. "
        f"Submit and return the resulting vendor-portal URL or confirmation page."
    )
    result = await ctx.browser.run(task=task, max_steps=30)
    return {
        "listing_url": result.get("output", ""),
        "success": bool(result.get("success")),
    }
