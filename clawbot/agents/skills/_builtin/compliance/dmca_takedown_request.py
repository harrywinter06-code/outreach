META = {
    "name": "dmca_takedown_request", "builtin": True,
    "description": "Send a formal DMCA takedown notice email to a host's designated agent. "
                   "Fills the standard six-element template required by 17 USC 512(c)(3).",
    "params": {
        "to": "str", "infringing_url": "str", "original_work_url": "str",
        "complainant_name": "str", "complainant_email": "str",
        "complainant_address": "str",
    },
    "returns": {"id": "str", "ok": "bool"},
    "cost_estimate_usd": 0.0, "timeout_s": 20.0,
}


async def run(
    ctx, to: str, infringing_url: str, original_work_url: str,
    complainant_name: str, complainant_email: str, complainant_address: str,
) -> dict:
    subject = f"DMCA Takedown Notice — {infringing_url}"
    body = (
        "Dear DMCA Designated Agent,\n\n"
        "This is a DMCA takedown notice under 17 U.S.C. § 512(c)(3).\n\n"
        "1. I am authorised to act on behalf of the copyright owner.\n\n"
        f"2. The original copyrighted work is located at: {original_work_url}\n\n"
        f"3. The material I claim infringes that work is located at: {infringing_url}\n\n"
        f"4. My contact details are:\n   Name: {complainant_name}\n"
        f"   Email: {complainant_email}\n   Address: {complainant_address}\n\n"
        "5. I have a good-faith belief that use of the material described above is "
        "not authorised by the copyright owner, its agent, or the law.\n\n"
        "6. I declare under penalty of perjury that the information in this notice "
        "is accurate and that I am the owner, or authorised to act on behalf of the "
        "owner, of an exclusive right that is allegedly infringed.\n\n"
        f"Signed,\n{complainant_name}\n"
    )
    result = await ctx.email.send(to=to, subject=subject, body_text=body)
    return {"id": result.get("id", ""), "ok": bool(result.get("id"))}
