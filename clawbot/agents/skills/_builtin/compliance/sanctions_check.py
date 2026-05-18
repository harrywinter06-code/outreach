META = {
    "name": "sanctions_check", "builtin": True,
    "description": "Screen a name against the OFAC Specially Designated Nationals (SDN) list via "
                   "the U.S. Treasury's free public search endpoint. Returns matches with score.",
    "params": {"name": "str", "minimum_score": "int"},
    "returns": {"matches": "list", "is_match": "bool"},
    "cost_estimate_usd": 0.0, "timeout_s": 15.0,
}


async def run(ctx, name: str, minimum_score: int = 85) -> dict:
    import json as _json
    url = (
        f"https://search.ofac.treas.gov/api/v1/search?name={name}"
        f"&minScore={minimum_score}&types=individual,entity"
    )
    resp = await ctx.http.get(url)
    try:
        data = _json.loads(resp.get("text") or "{}")
    except ValueError:
        data = {}
    matches = data.get("matches", []) or data.get("results", [])
    return {"matches": matches, "is_match": bool(matches)}
