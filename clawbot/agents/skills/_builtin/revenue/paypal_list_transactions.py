META = {
    "name": "paypal_list_transactions", "builtin": True,
    "description": "List PayPal transactions in a date range. Dates are ISO 8601 with timezone (e.g., '2026-05-01T00:00:00-0000').",
    "params": {"start_date": "str", "end_date": "str"},
    "returns": {"transactions": "list", "count": "int"},
}


async def run(ctx, start_date: str, end_date: str) -> dict:
    txns = await ctx.revenue.paypal_list_transactions(
        start_date=start_date, end_date=end_date,
    )
    return {"transactions": txns, "count": len(txns)}
