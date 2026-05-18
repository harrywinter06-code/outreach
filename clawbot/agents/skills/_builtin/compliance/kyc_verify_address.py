META = {
    "name": "kyc_verify_address", "builtin": True,
    "description": "Verify a person's address via Onfido. Needs ONFIDO_API_TOKEN. "
                   "Creates a document check and returns the verification id + status.",
    "params": {
        "applicant_id": "str", "address_line1": "str", "city": "str",
        "postcode": "str", "country_code": "str",
    },
    "returns": {"check_id": "str", "status": "str"},
    "cost_estimate_usd": 0.0, "timeout_s": 30.0,
}


async def run(
    ctx, applicant_id: str, address_line1: str, city: str,
    postcode: str, country_code: str,
) -> dict:
    import json as _json
    token = ctx.secret.get("ONFIDO_API_TOKEN")
    payload = {
        "applicant_id": applicant_id,
        "report_names": ["proof_of_address"],
        "address": {
            "line1": address_line1, "town": city,
            "postcode": postcode, "country": country_code,
        },
    }
    resp = await ctx.http.post(
        "https://api.onfido.com/v3.6/checks",
        json=payload,
        headers={
            "Authorization": f"Token token={token}",
            "Content-Type": "application/json",
        },
    )
    try:
        data = _json.loads(resp.get("text") or "{}")
    except ValueError:
        data = {}
    return {
        "check_id": str(data.get("id", "")),
        "status": data.get("status", "unknown"),
    }
