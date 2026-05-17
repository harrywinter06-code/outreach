META = {
    "name": "account_get", "builtin": True,
    "description": "Fetch creds for one (service, email) account from the vault. "
                   "Returns found=False if no such account.",
    "params": {"service": "str", "email": "str"},
    "returns": {"found": "bool", "service": "str", "email": "str",
                "password": "str", "cookies_json": "str", "status": "str"},
    "cost_estimate_usd": 0.0, "timeout_s": 5.0,
}


async def run(ctx, service: str, email: str) -> dict:
    rec = await ctx.accounts.get_account(service=service, email=email)
    if rec is None:
        return {
            "found": False, "service": service, "email": email,
            "password": "", "cookies_json": "", "status": "missing",
        }
    return {
        "found": True,
        "service": rec["service"], "email": rec["email"],
        "password": rec["password"], "cookies_json": rec["cookies_json"],
        "status": rec["status"],
    }
