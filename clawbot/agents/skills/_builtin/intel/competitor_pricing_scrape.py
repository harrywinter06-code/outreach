import json

META = {
    "name": "competitor_pricing_scrape", "builtin": True,
    "description": "Drive a browser across a list of competitor pricing pages and extract their plan tiers + prices.",
    "params": {"urls": "list"},
    "returns": {"competitors": "list"},
    "cost_estimate_usd": 0.05, "timeout_s": 300.0,
}


async def run(ctx, urls: list) -> dict:
    competitors: list[dict] = []
    for url in urls:
        task = (
            f"Visit {url}. Extract every visible pricing plan as JSON. "
            f"Return ONLY a single JSON array on one line of objects with keys "
            f"'tier', 'price', 'period', 'features'. No prose, no markdown fences."
        )
        result = await ctx.browser.run(task=task, max_steps=15)
        plans: list = []
        raw = str(result.get("output", "")).strip()
        if result.get("success") and raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    plans = parsed
            except (ValueError, json.JSONDecodeError):
                plans = []
        competitors.append({"url": url, "plans": plans})
    return {"competitors": competitors}
