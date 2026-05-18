"""Infra status report: system health snapshot."""
from datetime import datetime

META = {
    "name": "infra_status_report",
    "builtin": True,
    "description": "Collect system health metrics and compose a status report.",
    "params": {},
    "returns": {
        "timestamp": "str",
        "db_health": "dict",
        "skill_calls_last_hour": "int",
        "ok": "bool",
    },
}


async def run(ctx) -> dict:
    """Gather current system health metrics.

    Combines DB health check with recent activity signals (skill calls as liveness proxy).
    """
    timestamp = datetime.utcnow().isoformat() + "Z"
    skill_calls_last_hour = 0
    db_health = {"ok": False, "latency_ms": 0, "error": "not checked"}

    # Check DB health
    try:
        db_rows = await ctx.sql.query(
            "SELECT 1 AS one"
        )
        if db_rows and len(db_rows) > 0:
            db_health = {"ok": True, "latency_ms": 0, "error": ""}
        else:
            db_health = {
                "ok": False,
                "latency_ms": 0,
                "error": "query returned no rows",
            }
    except Exception as exc:
        db_health = {
            "ok": False,
            "latency_ms": 0,
            "error": str(exc)[:200],
        }

    # Recent activity — skill_calls in the last hour as a liveness proxy
    try:
        rows = await ctx.sql.query(
            "SELECT COUNT(*) AS n FROM skill_calls "
            "WHERE called_at > NOW() - INTERVAL '1 hour'"
        )
        if rows and len(rows) > 0:
            skill_calls_last_hour = int(rows[0].get("n", 0))
    except Exception:
        skill_calls_last_hour = 0

    # Overall ok: DB is healthy
    overall_ok = db_health.get("ok", False)

    return {
        "timestamp": timestamp,
        "db_health": db_health,
        "skill_calls_last_hour": skill_calls_last_hour,
        "ok": overall_ok,
    }
