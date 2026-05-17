META = {
    "name": "account_mark_zombie", "builtin": True,
    "description": "Mark an account as zombie (manual intervention needed). "
                   "Use when a service-side issue prevents normal recovery.",
    "params": {"service": "str", "email": "str", "reason": "str"},
    "returns": {"service": "str", "email": "str", "status": "str"},
    "cost_estimate_usd": 0.0, "timeout_s": 5.0,
}


async def run(ctx, service: str, email: str, reason: str) -> dict:
    result = await ctx.accounts.mark_zombie(
        service=service, email=email, reason=reason,
    )
    return {
        "service": result["service"], "email": result["email"],
        "status": result["status"],
    }
