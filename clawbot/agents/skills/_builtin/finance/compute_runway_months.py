META = {
    "name": "compute_runway_months", "builtin": True,
    "description": "Compute cash on hand divided by 30-day burn. Returns months remaining + burn rate. "
                   "Reads recent expenses from the ledger table. Returns 999 months when burn is zero "
                   "(no expenses yet or ledger table absent).",
    "params": {"cash_gbp": "float"},
    "returns": {"months": "float", "burn_30d_gbp": "float"},
    "cost_estimate_usd": 0.0, "timeout_s": 10.0,
}


async def run(ctx, cash_gbp: float) -> dict:
    try:
        rows = await ctx.sql.query(
            "SELECT COALESCE(SUM(amount_gbp), 0) AS spent FROM ledger "
            "WHERE entry_type = 'expense' "
            "AND created_at > NOW() - INTERVAL '30 days'"
        )
        burn = float(rows[0]["spent"] or 0) if rows else 0.0
    except Exception:
        burn = 0.0
    months = (cash_gbp / burn) if burn > 0 else 999.0
    return {"months": round(months, 2), "burn_30d_gbp": round(burn, 2)}
