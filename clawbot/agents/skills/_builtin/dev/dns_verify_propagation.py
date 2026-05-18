META = {
    "name": "dns_verify_propagation", "builtin": True,
    "description": "Resolve a hostname via Google's public DoH resolver and check that the answer "
                   "matches expected_value. Returns matches=True only if at least one answer line "
                   "equals expected_value.",
    "params": {"name": "str", "record_type": "str", "expected_value": "str"},
    "returns": {"matches": "bool", "answers": "list"},
    "cost_estimate_usd": 0.0, "timeout_s": 15.0,
}


async def run(ctx, name: str, record_type: str, expected_value: str) -> dict:
    import json as _json
    resp = await ctx.http.get(
        f"https://dns.google/resolve?name={name}&type={record_type}",
        headers={"Accept": "application/dns-json"},
    )
    try:
        data = _json.loads(resp.get("text") or "{}")
    except ValueError:
        data = {}
    answers = [a.get("data", "") for a in data.get("Answer", [])]
    cleaned_expected = expected_value.strip().rstrip(".")
    matches = any(a.strip().rstrip(".") == cleaned_expected for a in answers)
    return {"matches": matches, "answers": answers}
