META = {
    "name": "freeagent_record_expense", "builtin": True,
    "description": "Record an expense in FreeAgent against a category. Needs FREEAGENT_OAUTH_TOKEN.",
    "params": {
        "category_url": "str", "dated_on": "str", "gross_value": "float",
        "description": "str", "currency": "str",
    },
    "returns": {"id": "str", "url": "str"},
    "cost_estimate_usd": 0.0, "timeout_s": 20.0,
}


async def run(
    ctx, category_url: str, dated_on: str, gross_value: float,
    description: str, currency: str,
) -> dict:
    import json as _json
    token = ctx.secret.get("FREEAGENT_OAUTH_TOKEN")
    payload = {
        "expense": {
            "category": category_url,
            "dated_on": dated_on,
            "gross_value": f"{gross_value:.2f}",
            "description": description,
            "currency": currency,
        }
    }
    resp = await ctx.http.post(
        "https://api.freeagent.com/v2/expenses",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        data = _json.loads(resp.get("text") or "{}")
    except ValueError:
        data = {}
    exp = data.get("expense", {})
    return {
        "id": str(exp.get("url", "").split("/")[-1]),
        "url": exp.get("url", ""),
    }
