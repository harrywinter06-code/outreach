META = {
    "name": "infra_redis_health", "builtin": True,
    "description": "Verify Redis bus reachability by publishing a heartbeat. "
                   "Returns {ok: bool, latency_ms: int, error: str}.",
    "params": {},
    "returns": {"ok": "bool", "latency_ms": "int", "error": "str"},
    "cost_estimate_usd": 0.0, "timeout_s": 10.0,
}


async def run(ctx) -> dict:
    from datetime import datetime as _datetime, UTC as _UTC
    start = _datetime.now(_UTC)
    try:
        await ctx.bus.publish("infra.heartbeat", {"from": "infra_redis_health"})
        elapsed = (_datetime.now(_UTC) - start).total_seconds() * 1000
        return {
            "ok": True,
            "latency_ms": int(elapsed),
            "error": "",
        }
    except Exception as exc:
        elapsed = (_datetime.now(_UTC) - start).total_seconds() * 1000
        return {
            "ok": False,
            "latency_ms": int(elapsed),
            "error": str(exc)[:200],
        }
