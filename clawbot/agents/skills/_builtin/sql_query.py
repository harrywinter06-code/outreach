META = {
    "name": "sql_query", "builtin": True,
    "description": "Run a parameterized SELECT against the agent DB. DDL rejected.",
    "params": {"sql": "str", "args": "list"},
    "returns": {"rows": "list"},
}


async def run(ctx, sql: str, args: list | None = None) -> dict:
    args = args or []
    rows = await ctx.sql.query(sql, *args)
    return {"rows": rows}
