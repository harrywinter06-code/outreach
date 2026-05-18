import json

META = {
    "name": "lighthouse_audit", "builtin": True,
    "description": "Run a PageSpeed Insights audit (Google Lighthouse) for a URL. Key-less but rate-limited; pass PSI_API_KEY via secret for higher quota.",
    "params": {"url": "str", "strategy": "str"},
    "returns": {"performance": "float", "accessibility": "float", "seo": "float", "best_practices": "float", "status": "int"},
    "cost_estimate_usd": 0.0, "timeout_s": 90.0,
}


async def run(ctx, url: str, strategy: str = "mobile") -> dict:
    try:
        key = ctx.secret.get("PSI_API_KEY")
    except PermissionError:
        key = ""
    encoded = url.replace(":", "%3A").replace("/", "%2F")
    qs = (
        f"url={encoded}&strategy={strategy}"
        f"&category=performance&category=accessibility&category=seo&category=best-practices"
    )
    if key:
        qs += f"&key={key}"
    resp = await ctx.http.get(
        f"https://www.googleapis.com/pagespeedonline/v5/runPagespeed?{qs}",
    )
    text = str(resp.get("text", ""))
    scores = {"performance": 0.0, "accessibility": 0.0, "seo": 0.0, "best_practices": 0.0}
    if resp.get("status") == 200 and text:
        try:
            categories = json.loads(text).get("lighthouseResult", {}).get("categories", {})
            for key_, slot in (("performance", "performance"),
                               ("accessibility", "accessibility"),
                               ("seo", "seo"),
                               ("best-practices", "best_practices")):
                cat = categories.get(key_)
                if cat and cat.get("score") is not None:
                    scores[slot] = float(cat["score"])
        except (ValueError, json.JSONDecodeError, TypeError):
            pass
    return {**scores, "status": int(resp.get("status", 0))}
