META = {
    "name": "hmrc_check_vat_number", "builtin": True,
    "description": "Verify a UK VAT number against HMRC's public Check VAT Number service. "
                   "No auth needed. Returns name, address, and whether the number is registered.",
    "params": {"vat_number": "str"},
    "returns": {"valid": "bool", "name": "str", "address": "str"},
    "cost_estimate_usd": 0.0, "timeout_s": 15.0,
}


async def run(ctx, vat_number: str) -> dict:
    import json as _json
    cleaned = vat_number.replace(" ", "").replace("-", "").upper()
    if cleaned.startswith("GB"):
        cleaned = cleaned[2:]
    url = (
        f"https://api.service.hmrc.gov.uk/organisations/vat/"
        f"check-vat-number/lookup/{cleaned}"
    )
    resp = await ctx.http.get(url, headers={"Accept": "application/vnd.hmrc.2.0+json"})
    if int(resp.get("status", 0)) >= 400:
        return {"valid": False, "name": "", "address": ""}
    try:
        data = _json.loads(resp.get("text") or "{}")
    except ValueError:
        data = {}
    target = data.get("target", {})
    address = target.get("address", {})
    address_lines = [
        address.get("line1", ""), address.get("line2", ""),
        address.get("line3", ""), address.get("line4", ""),
        address.get("postcode", ""), address.get("countryCode", ""),
    ]
    return {
        "valid": bool(target.get("name")),
        "name": target.get("name", ""),
        "address": ", ".join(p for p in address_lines if p),
    }
