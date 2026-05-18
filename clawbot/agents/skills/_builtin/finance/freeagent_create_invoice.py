META = {
    "name": "freeagent_create_invoice", "builtin": True,
    "description": "Create an invoice in FreeAgent. Needs FREEAGENT_OAUTH_TOKEN. "
                   "Returns invoice id + url.",
    "params": {
        "contact_url": "str", "dated_on": "str", "payment_terms_in_days": "int",
        "currency": "str", "items": "list",
    },
    "returns": {"id": "str", "url": "str", "reference": "str"},
    "cost_estimate_usd": 0.0, "timeout_s": 20.0,
}


async def run(
    ctx, contact_url: str, dated_on: str, payment_terms_in_days: int,
    currency: str, items: list | None = None,
) -> dict:
    import json as _json
    token = ctx.secret.get("FREEAGENT_OAUTH_TOKEN")
    payload = {
        "invoice": {
            "contact": contact_url,
            "dated_on": dated_on,
            "payment_terms_in_days": payment_terms_in_days,
            "currency": currency,
            "invoice_items": items or [],
        }
    }
    resp = await ctx.http.post(
        "https://api.freeagent.com/v2/invoices",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        data = _json.loads(resp.get("text") or "{}")
    except ValueError:
        data = {}
    inv = data.get("invoice", {})
    return {
        "id": str(inv.get("url", "").split("/")[-1]),
        "url": inv.get("url", ""),
        "reference": inv.get("reference", ""),
    }
