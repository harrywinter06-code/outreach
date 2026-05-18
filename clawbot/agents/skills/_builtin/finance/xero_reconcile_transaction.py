META = {
    "name": "xero_reconcile_transaction", "builtin": True,
    "description": "Match a bank-feed transaction to an existing Xero invoice and mark it reconciled. "
                   "Needs XERO_OAUTH_TOKEN and XERO_TENANT_ID.",
    "params": {
        "bank_transaction_id": "str", "invoice_id": "str", "amount": "float",
    },
    "returns": {"status": "str", "reconciled_id": "str"},
    "cost_estimate_usd": 0.0, "timeout_s": 20.0,
}


async def run(
    ctx, bank_transaction_id: str, invoice_id: str, amount: float,
) -> dict:
    import json as _json
    token = ctx.secret.get("XERO_OAUTH_TOKEN")
    tenant = ctx.secret.get("XERO_TENANT_ID")
    payload = {
        "Payments": [{
            "Invoice": {"InvoiceID": invoice_id},
            "Account": {"AccountID": bank_transaction_id},
            "Amount": amount,
        }],
    }
    resp = await ctx.http.post(
        "https://api.xero.com/api.xro/2.0/Payments",
        json=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Xero-tenant-id": tenant,
            "Accept": "application/json",
        },
    )
    try:
        data = _json.loads(resp.get("text") or "{}")
    except ValueError:
        data = {}
    payments = data.get("Payments", [])
    if payments:
        return {"status": payments[0].get("Status", "OK"), "reconciled_id": payments[0].get("PaymentID", "")}
    return {"status": "FAILED", "reconciled_id": ""}
