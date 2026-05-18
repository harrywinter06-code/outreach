META = {
    "name": "gdpr_data_export", "builtin": True,
    "description": "Dump all PII rows matching a user_id across configured tables (leads, tickets, "
                   "accounts). Returns a structured export for sending to the data subject. "
                   "Read-only — no mutation.",
    "params": {"user_id": "str", "user_email": "str"},
    "returns": {"export": "dict", "row_count": "int"},
    "cost_estimate_usd": 0.0, "timeout_s": 30.0,
}


async def run(ctx, user_id: str, user_email: str = "") -> dict:
    export: dict[str, list] = {}
    total = 0

    targets = [
        ("leads", "SELECT * FROM leads WHERE user_id = $1 OR email = $2", [user_id, user_email]),
        ("tickets", "SELECT * FROM tickets WHERE assigned_to = $1", [user_id]),
        ("knowledge",
         "SELECT id, content, metadata, created_at FROM knowledge "
         "WHERE metadata->>'user_id' = $1 OR metadata->>'email' = $2",
         [user_id, user_email]),
    ]
    for table, sql, args in targets:
        try:
            rows = await ctx.sql.query(sql, *args)
        except Exception:
            rows = []
        export[table] = rows
        total += len(rows)
    return {"export": export, "row_count": total}
