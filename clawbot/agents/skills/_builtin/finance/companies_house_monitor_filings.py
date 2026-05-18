META = {
    "name": "companies_house_monitor_filings", "builtin": True,
    "description": "Diff the current filing history against the last stored snapshot for a company. "
                   "Returns only new filings since last poll. Snapshot stored at "
                   "data/ch_snapshots/<company_number>.json.",
    "params": {"company_number": "str"},
    "returns": {"new_filings": "list", "is_first_seen": "bool"},
    "cost_estimate_usd": 0.0, "timeout_s": 20.0,
}


async def run(ctx, company_number: str) -> dict:
    import base64 as _b64
    import json as _json
    api_key = ctx.secret.get("COMPANIES_HOUSE_API_KEY")
    auth = _b64.b64encode(f"{api_key}:".encode()).decode()
    url = (
        f"https://api.company-information.service.gov.uk/company/"
        f"{company_number}/filing-history?items_per_page=50"
    )
    resp = await ctx.http.get(url, headers={"Authorization": f"Basic {auth}"})
    try:
        current = _json.loads(resp.get("text") or "{}").get("items", [])
    except ValueError:
        current = []
    current_ids = {f.get("transaction_id") for f in current if f.get("transaction_id")}

    snap_path = f"data/ch_snapshots/{company_number}.json"
    try:
        prior_raw = await ctx.fs.read(snap_path)
        prior_ids = set(_json.loads(prior_raw or "[]"))
        is_first = False
    except Exception:
        prior_ids = set()
        is_first = True

    new_filings = [f for f in current if f.get("transaction_id") not in prior_ids]
    await ctx.fs.write(snap_path, _json.dumps(sorted(current_ids)))
    return {"new_filings": new_filings, "is_first_seen": is_first}
