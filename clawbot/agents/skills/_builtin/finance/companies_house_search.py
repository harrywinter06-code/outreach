META = {
    "name": "companies_house_search", "builtin": True,
    "description": "Search UK Companies House by company name. Returns matching companies. "
                   "Free public API; requires COMPANIES_HOUSE_API_KEY (HTTP Basic, key as username).",
    "params": {"query": "str", "items_per_page": "int"},
    "returns": {"items": "list", "total_results": "int"},
    "cost_estimate_usd": 0.0, "timeout_s": 15.0,
}


async def run(ctx, query: str, items_per_page: int = 20) -> dict:
    import base64 as _b64
    import json as _json
    api_key = ctx.secret.get("COMPANIES_HOUSE_API_KEY")
    auth = _b64.b64encode(f"{api_key}:".encode()).decode()
    url = (
        f"https://api.company-information.service.gov.uk/search/companies"
        f"?q={query}&items_per_page={items_per_page}"
    )
    resp = await ctx.http.get(url, headers={"Authorization": f"Basic {auth}"})
    try:
        data = _json.loads(resp.get("text") or "{}")
    except ValueError:
        data = {}
    return {
        "items": data.get("items", []),
        "total_results": int(data.get("total_results", 0)),
    }
