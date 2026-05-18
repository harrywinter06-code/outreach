import json

META = {
    "name": "crunchbase_lookup", "builtin": True,
    "description": "Look up a company on Crunchbase. Requires CRUNCHBASE_API_KEY; returns funding total, last round, headcount.",
    "params": {"company_slug": "str"},
    "returns": {"name": "str", "funding_total_usd": "float", "last_round": "str", "employee_count": "str", "status": "int"},
    "cost_estimate_usd": 0.001, "timeout_s": 30.0,
}


async def run(ctx, company_slug: str) -> dict:
    key = ctx.secret.get("CRUNCHBASE_API_KEY")
    empty = {"name": "", "funding_total_usd": 0.0, "last_round": "",
             "employee_count": "", "status": 401}
    if not key:
        return empty
    resp = await ctx.http.get(
        f"https://api.crunchbase.com/api/v4/entities/organizations/{company_slug}"
        f"?card_ids=fields&field_ids=name,funding_total,last_funding_type,num_employees_enum",
        headers={"X-Cb-User-Key": key},
    )
    text = str(resp.get("text", ""))
    status = int(resp.get("status", 0))
    if status != 200 or not text:
        return {**empty, "status": status}
    try:
        props = json.loads(text).get("properties", {})
    except (ValueError, json.JSONDecodeError):
        return {**empty, "status": status}
    funding = 0.0
    ft = props.get("funding_total") or {}
    if isinstance(ft, dict) and isinstance(ft.get("value_usd"), (int, float)):
        funding = float(ft["value_usd"])
    return {
        "name": str(props.get("name", "")),
        "funding_total_usd": funding,
        "last_round": str(props.get("last_funding_type", "")),
        "employee_count": str(props.get("num_employees_enum", "")),
        "status": status,
    }
