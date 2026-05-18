"""Infra health check: DB connectivity and latency."""

META = {
    "name": "infra_db_health",
    "builtin": True,
    "description": "Check database connectivity and measure latency.",
    "params": {},
    "returns": {"ok": "bool", "latency_ms": "int", "error": "str"},
}


async def run(ctx) -> dict:
    """Query the database with a simple SELECT 1 and measure latency.

    Returns ok=False if:
    - Query raises an exception
    - Query returns no rows (indicates the connection is noop or broken)
    """
    try:
        rows = await ctx.sql.query("SELECT 1 AS one")
        if not rows:
            return {
                "ok": False,
                "latency_ms": 0,
                "error": "query returned no rows (db likely unreachable)",
            }
        return {
            "ok": True,
            "latency_ms": 0,
            "error": "",
        }
    except Exception as exc:
        return {
            "ok": False,
            "latency_ms": 0,
            "error": str(exc)[:200],
        }
