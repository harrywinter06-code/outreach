META = {
    "name": "prnewswire_submit", "builtin": True,
    "description": "Submit a press release via PR Newswire. Uses the partner API if "
                   "PRNEWSWIRE_API_KEY is set, otherwise falls back to the browser submission form.",
    "params": {
        "headline": "str", "subheadline": "str", "body_text": "str",
        "release_date_iso": "str", "categories": "list",
    },
    "returns": {"release_id": "str", "success": "bool"},
    "cost_estimate_usd": 0.0, "timeout_s": 240.0,
}


async def run(
    ctx, headline: str, subheadline: str, body_text: str,
    release_date_iso: str, categories: list | None = None,
) -> dict:
    categories = categories or []
    api_key = ctx.secret.get("PRNEWSWIRE_API_KEY") if hasattr(ctx, "secret") else ""
    if api_key:
        resp = await ctx.http.post(
            "https://api.prnewswire.com/v1/releases",
            json={
                "headline": headline,
                "subheadline": subheadline,
                "body": body_text,
                "release_date": release_date_iso,
                "categories": categories,
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        import json as _json
        try:
            data = _json.loads(resp.get("text") or "{}")
        except ValueError:
            data = {}
        return {
            "release_id": str(data.get("id", "")),
            "success": 200 <= int(resp.get("status", 0)) < 300,
        }
    task = (
        f"Go to https://www.prnewswire.com/account/online-member-center/. "
        f"Click 'Send a Release'. Fill: headline {headline!r}, "
        f"subheadline {subheadline!r}, release-date {release_date_iso}, "
        f"categories {categories}. Paste body:\n\n{body_text[:6000]}\n\n"
        f"Submit. Return the resulting release ID or confirmation URL."
    )
    result = await ctx.browser.run(task=task, max_steps=35)
    return {
        "release_id": result.get("output", ""),
        "success": bool(result.get("success")),
    }
