import json

META = {
    "name": "gsc_query", "builtin": True,
    "description": "Query Google Search Console for top queries/pages over a date range. Requires GSC_ACCESS_TOKEN (pre-acquired OAuth bearer for the service account).",
    "params": {"site_url": "str", "start_date": "str", "end_date": "str", "dimensions": "list", "row_limit": "int"},
    "returns": {"rows": "list", "status": "int"},
    "cost_estimate_usd": 0.0, "timeout_s": 30.0,
}


async def run(ctx, site_url: str, start_date: str, end_date: str,
              dimensions: list | None = None, row_limit: int = 100) -> dict:
    token = ctx.secret.get("GSC_ACCESS_TOKEN")
    if not token:
        return {"rows": [], "status": 401}
    body = {
        "startDate": start_date, "endDate": end_date,
        "dimensions": dimensions or ["query"],
        "rowLimit": row_limit,
    }
    encoded = site_url.replace(":", "%3A").replace("/", "%2F")
    resp = await ctx.http.post(
        f"https://www.googleapis.com/webmasters/v3/sites/{encoded}/searchAnalytics/query",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
    )
    text = str(resp.get("text", ""))
    rows: list = []
    if resp.get("status") == 200 and text:
        try:
            rows = json.loads(text).get("rows", [])
        except (ValueError, json.JSONDecodeError):
            rows = []
    return {"rows": rows, "status": int(resp.get("status", 0))}
