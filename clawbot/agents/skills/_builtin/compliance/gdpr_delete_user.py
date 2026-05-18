META = {
    "name": "gdpr_delete_user", "builtin": True,
    "description": "Erase all rows referencing a user_id across PII tables (leads, tickets, "
                   "knowledge metadata). Operator-gated — every call requires Telegram approval "
                   "because this is a destructive, irreversible operation.",
    "params": {"user_id": "str", "user_email": "str"},
    "returns": {"deleted_count": "int", "tables_affected": "list"},
    "cost_estimate_usd": 0.0, "timeout_s": 60.0, "requires_approval": True,
}


async def run(ctx, user_id: str, user_email: str = "") -> dict:
    targets = [
        ("leads", "DELETE FROM leads WHERE user_id = $1 OR email = $2 RETURNING id",
         [user_id, user_email]),
        ("tickets", "DELETE FROM tickets WHERE assigned_to = $1 RETURNING id", [user_id]),
        ("knowledge",
         "DELETE FROM knowledge WHERE metadata->>'user_id' = $1 OR metadata->>'email' = $2 "
         "RETURNING id",
         [user_id, user_email]),
    ]
    total = 0
    affected: list = []
    for table, sql, args in targets:
        try:
            rows = await ctx.sql.query(sql, *args)
        except Exception:
            continue
        if rows:
            affected.append(table)
            total += len(rows)
    return {"deleted_count": total, "tables_affected": affected}
