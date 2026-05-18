import json

META = {
    "name": "glassdoor_scrape_company", "builtin": True,
    "description": "Drive a browser to a Glassdoor company page, extract headcount range, rating, recent review themes.",
    "params": {"company_slug": "str"},
    "returns": {"rating": "float", "headcount_range": "str", "review_themes": "list"},
    "cost_estimate_usd": 0.03, "timeout_s": 180.0,
}


async def run(ctx, company_slug: str) -> dict:
    url = f"https://www.glassdoor.com/Overview/Working-at-{company_slug}.htm"
    task = (
        f"Visit {url}. Extract: 'rating' (float, overall), "
        f"'headcount_range' (string like '51-200'), "
        f"'review_themes' (list of up to 5 short phrases summarising recurring praise/complaints). "
        f"Return ONLY a single JSON object on one line. No prose, no markdown fences."
    )
    result = await ctx.browser.run(task=task, max_steps=20)
    raw = str(result.get("output", "")).strip()
    rating = 0.0
    headcount = ""
    themes: list = []
    if result.get("success") and raw:
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                if isinstance(data.get("rating"), (int, float)):
                    rating = float(data["rating"])
                if isinstance(data.get("headcount_range"), str):
                    headcount = data["headcount_range"]
                if isinstance(data.get("review_themes"), list):
                    themes = [str(t) for t in data["review_themes"][:5]]
        except (ValueError, json.JSONDecodeError):
            pass
    return {"rating": rating, "headcount_range": headcount, "review_themes": themes}
