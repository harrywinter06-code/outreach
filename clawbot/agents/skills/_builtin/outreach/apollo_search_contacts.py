META = {
    "name": "apollo_search_contacts", "builtin": True,
    "description": "Search Apollo.io for contacts by titles + organisation domain. Requires APOLLO_API_KEY.",
    "params": {"person_titles": "list", "organization_domains": "list", "page": "int"},
    "returns": {"contacts": "list", "count": "int"},
}


async def run(
    ctx, person_titles: list | None = None,
    organization_domains: list | None = None,
    page: int = 1,
) -> dict:
    import json as _json
    key = ctx.secret.get("APOLLO_API_KEY")
    if not key:
        return {"contacts": [], "count": 0}
    payload = {
        "person_titles": person_titles or [],
        "q_organization_domains": "\n".join(organization_domains or []),
        "page": max(1, int(page)),
        "per_page": 25,
    }
    res = await ctx.http.post(
        "https://api.apollo.io/v1/mixed_people/search",
        json=payload,
        headers={
            "X-Api-Key": key,
            "Content-Type": "application/json",
            "Cache-Control": "no-cache",
        },
    )
    try:
        body = _json.loads(res.get("text", "{}"))
        people = body.get("people", []) or []
    except _json.JSONDecodeError:
        people = []
    contacts = [
        {"name": p.get("name", ""), "title": p.get("title", ""),
         "email": p.get("email", ""), "company": p.get("organization", {}).get("name", "")}
        for p in people
    ]
    return {"contacts": contacts, "count": len(contacts)}
