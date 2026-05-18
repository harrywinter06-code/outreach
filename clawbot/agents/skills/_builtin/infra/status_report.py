META = {
    "name": "infra_status_report", "builtin": True,
    "description": "Rolled-up infrastructure health. Composes db_health + "
                   "redis_health + recent skill_calls count. Use as the first "
                   "check before any deploy or destructive action.",
    "params": {},
    "returns": {
        "db_ok": "bool", "redis_ok": "bool",
        "db_latency_ms": "int", "redis_latency_ms": "int",
        "skill_calls_last_hour": "int",
    },
    "cost_estimate_usd": 0.0, "timeout_s": 15.0,
}


async def run(ctx) -> dict:
    from datetime import datetime as _datetime, UTC as _UTC
    # DB check
    db_start = _datetime.now(_UTC)
    db_ok = False
    try:
        await ctx.sql.query("SELECT 1 AS one")
        db_ok = True
    except Exception:
        db_ok = False
    db_latency_ms = int((_datetime.now(_UTC) - db_start).total_seconds() * 1000)

    # Redis check (via bus publish)
    redis_start = _datetime.now(_UTC)
    redis_ok = False
    try:
        await ctx.bus.publish("infra.heartbeat", {"from": "infra_status_report"})
        redis_ok = True
    except Exception:
        redis_ok = False
    redis_latency_ms = int((_datetime.now(_UTC) - redis_start).total_seconds() * 1000)

    # Recent activity — skill_calls in the last hour as a liveness proxy
    skill_calls_last_hour = 0
    try:
        rows = await ctx.sql.query(
            "SELECT COUNT(*) AS n FROM skill_calls "
            "WHERE created_at > NOW() - INTERVAL '1 hour'"
        )
        if rows and len(rows) > 0:
            skill_calls_last_hour = int(rows[0].get("n", 0))
    except Exception:
        skill_calls_last_hour = 0

    return {
        "db_ok": db_ok,
        "redis_ok": redis_ok,
        "db_latency_ms": db_latency_ms,
        "redis_latency_ms": redis_latency_ms,
        "skill_calls_last_hour": skill_calls_last_hour,
    }
