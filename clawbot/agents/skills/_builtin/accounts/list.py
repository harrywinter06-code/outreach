META = {
    "name": "account_list", "builtin": True,
    "description": "List all vaulted accounts, optionally filtered by status (live|zombie|revoked).",
    "params": {"status": "str"},
    "returns": {"count": "int", "accounts": "list"},
    "cost_estimate_usd": 0.0, "timeout_s": 5.0,
}


async def run(ctx, status: str = "") -> dict:
    rows = await ctx.accounts.list_accounts(status=status or None)
    return {"count": len(rows), "accounts": rows}
