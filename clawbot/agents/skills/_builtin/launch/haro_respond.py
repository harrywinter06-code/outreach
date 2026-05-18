META = {
    "name": "haro_respond", "builtin": True,
    "description": "Respond to a HARO / Help A Reporter Out query by emailing the journalist's "
                   "pitch address. The pitch address is in the daily HARO digest and is unique "
                   "per query. Subject and body MUST follow HARO's pitch format.",
    "params": {
        "pitch_email": "str", "query_id": "str", "subject_line": "str",
        "pitch_body": "str", "bio": "str",
    },
    "returns": {"id": "str", "ok": "bool"},
    "cost_estimate_usd": 0.0, "timeout_s": 20.0,
}


async def run(
    ctx, pitch_email: str, query_id: str, subject_line: str,
    pitch_body: str, bio: str = "",
) -> dict:
    final_subject = f"[HARO {query_id}] {subject_line}"
    full_body = (
        f"{pitch_body}\n\n"
        f"---\n"
        f"Bio: {bio}\n"
        if bio else
        f"{pitch_body}\n"
    )
    result = await ctx.email.send(
        to=pitch_email, subject=final_subject, body_text=full_body,
    )
    return {"id": result.get("id", ""), "ok": bool(result.get("id"))}
