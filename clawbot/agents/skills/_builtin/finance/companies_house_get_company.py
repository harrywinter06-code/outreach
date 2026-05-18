META = {
    "name": "companies_house_get_company", "builtin": True,
    "description": "Fetch the canonical Companies House profile for a UK company by its number.",
    "params": {"company_number": "str"},
    "returns": {"company": "dict"},
    "cost_estimate_usd": 0.0, "timeout_s": 15.0,
}


async def run(ctx, company_number: str) -> dict:
    import base64 as _b64
    import json as _json
    api_key = ctx.secret.get("COMPANIES_HOUSE_API_KEY")
    auth = _b64.b64encode(f"{api_key}:".encode()).decode()
    url = f"https://api.company-information.service.gov.uk/company/{company_number}"
    resp = await ctx.http.get(url, headers={"Authorization": f"Basic {auth}"})
    try:
        data = _json.loads(resp.get("text") or "{}")
    except ValueError:
        data = {}
    return {"company": data}
