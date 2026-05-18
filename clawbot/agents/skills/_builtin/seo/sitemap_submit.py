META = {
    "name": "sitemap_submit", "builtin": True,
    "description": "Ping Google and Bing to recrawl a sitemap. Both endpoints are public (no auth) and return 200 even when the sitemap is rejected — check the response text.",
    "params": {"sitemap_url": "str"},
    "returns": {"google_status": "int", "bing_status": "int"},
    "cost_estimate_usd": 0.0, "timeout_s": 30.0,
}


async def run(ctx, sitemap_url: str) -> dict:
    encoded = sitemap_url.replace(":", "%3A").replace("/", "%2F")
    g = await ctx.http.get(f"https://www.google.com/ping?sitemap={encoded}")
    b = await ctx.http.get(f"https://www.bing.com/ping?sitemap={encoded}")
    return {
        "google_status": int(g.get("status", 0)),
        "bing_status": int(b.get("status", 0)),
    }
