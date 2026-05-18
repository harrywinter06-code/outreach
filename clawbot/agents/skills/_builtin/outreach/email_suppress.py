META = {
    "name": "email_suppress", "builtin": True,
    "description": "Add an email to the suppression list so email_send_cold refuses to mail it. Idempotent.",
    "params": {"email": "str", "reason": "str"},
    "returns": {"email": "str", "suppressed": "bool"},
}


async def run(ctx, email: str, reason: str = "") -> dict:
    await ctx.sql.query(
        "INSERT INTO suppression (email, reason) VALUES ($1, $2) "
        "ON CONFLICT (email) DO UPDATE SET reason = EXCLUDED.reason",
        email.strip().lower(), reason,
    )
    return {"email": email.strip().lower(), "suppressed": True}
