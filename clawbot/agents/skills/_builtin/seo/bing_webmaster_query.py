import json

META = {
    "name": "bing_webmaster_query", "builtin": True,
    "description": "Query Bing Webmaster Tools for query stats on a site. Requires BING_WEBMASTER_KEY.",
    "params": {"site_url": "str"},
    "returns": {"queries": "list", "status": "int"},
    "cost_estimate_usd": 0.0, "timeout_s": 30.0,
}


async def run(ctx, site_url: str) -> dict:
    key = ctx.secret.get("BING_WEBMASTER_KEY")
    if not key:
        return {"queries": [], "status": 401}
    encoded = site_url.replace(":", "%3A").replace("/", "%2F")
    resp = await ctx.http.get(
        f"https://ssl.bing.com/webmaster/api.svc/json/GetQueryStats?siteUrl={encoded}&apikey={key}",
    )
    text = str(resp.get("text", ""))
    queries: list = []
    if resp.get("status") == 200 and text:
        try:
            queries = json.loads(text).get("d", [])
        except (ValueError, json.JSONDecodeError):
            queries = []
    return {"queries": queries, "status": int(resp.get("status", 0))}
