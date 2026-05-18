META = {
    "name": "support_canned_response", "builtin": True,
    "description": "Look up the closest prior resolved-ticket reply for a new inbound question "
                   "via vector search. Returns the top-1 suggested reply, or empty if none.",
    "params": {"question": "str"},
    "returns": {"suggested_reply": "str", "match_score": "float"},
    "cost_estimate_usd": 0.0, "timeout_s": 15.0,
}


async def run(ctx, question: str) -> dict:
    hits = await ctx.vector.search(question, k=1)
    if not hits:
        return {"suggested_reply": "", "match_score": 0.0}
    top = hits[0]
    metadata = top.get("metadata") or {}
    reply = metadata.get("resolution_reply") or top.get("content", "")
    return {
        "suggested_reply": reply,
        "match_score": float(top.get("score") or top.get("similarity") or 0.0),
    }
