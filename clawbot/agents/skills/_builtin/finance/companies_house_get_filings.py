META = {
    "name": "companies_house_get_filings", "builtin": True,
    "description": "Fetch the filing history for a UK company (accounts, confirmation statements, "
                   "officer changes, etc.) ordered most-recent first.",
    "params": {"company_number": "str", "items_per_page": "int"},
    "returns": {"items": "list", "total_count": "int"},
    "cost_estimate_usd": 0.0, "timeout_s": 15.0,
}


async def run(ctx, company_number: str, items_per_page: int = 25) -> dict:
    import base64 as _b64
    import json as _json
    api_key = ctx.secret.get("COMPANIES_HOUSE_API_KEY")
    auth = _b64.b64encode(f"{api_key}:".encode()).decode()
    url = (
        f"https://api.company-information.service.gov.uk/company/"
        f"{company_number}/filing-history?items_per_page={items_per_page}"
    )
    resp = await ctx.http.get(url, headers={"Authorization": f"Basic {auth}"})
    try:
        data = _json.loads(resp.get("text") or "{}")
    except ValueError:
        data = {}
    return {
        "items": data.get("items", []),
        "total_count": int(data.get("total_count", 0)),
    }
