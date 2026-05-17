META = {
    "name": "account_create", "builtin": True,
    "description": "Autonomously sign up for a service using catch-all email + vault. "
                   "Returns status=live on success or status=zombie if signup got stuck.",
    "params": {"service": "str", "signup_url": "str", "notes": "str"},
    "returns": {"status": "str", "service": "str", "email": "str"},
    "cost_estimate_usd": 0.05, "timeout_s": 180.0,
}


async def run(ctx, service: str, signup_url: str, notes: str = "") -> dict:
    result = await ctx.accounts.create_account(
        service=service, signup_url=signup_url, notes=notes,
    )
    return {
        "status": result.get("status", "unknown"),
        "service": result.get("service", service),
        "email": result.get("email", ""),
    }
