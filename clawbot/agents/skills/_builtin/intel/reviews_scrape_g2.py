import json

META = {
    "name": "reviews_scrape_g2", "builtin": True,
    "description": "Drive a browser to a G2 product review page, extract recent review titles + star ratings + sentiment.",
    "params": {"product_slug": "str", "max_reviews": "int"},
    "returns": {"reviews": "list", "average_rating": "float"},
    "cost_estimate_usd": 0.03, "timeout_s": 180.0,
}


async def run(ctx, product_slug: str, max_reviews: int = 20) -> dict:
    url = f"https://www.g2.com/products/{product_slug}/reviews"
    task = (
        f"Visit {url}. Extract up to {max_reviews} of the most recent reviews. "
        f"Return ONLY a single JSON object on one line with keys 'reviews' "
        f"(a list of objects with title, rating, body, date) and 'average_rating' (float). "
        f"No prose, no markdown fences."
    )
    result = await ctx.browser.run(task=task, max_steps=20)
    raw = str(result.get("output", "")).strip()
    reviews: list = []
    average = 0.0
    if result.get("success") and raw:
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                if isinstance(data.get("reviews"), list):
                    reviews = data["reviews"][:max_reviews]
                if isinstance(data.get("average_rating"), (int, float)):
                    average = float(data["average_rating"])
        except (ValueError, json.JSONDecodeError):
            pass
    return {"reviews": reviews, "average_rating": average}
