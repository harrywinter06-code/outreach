META = {
    "name": "worker_fire", "builtin": True,
    "description": "Deregister a worker. Cannot fire executives (ceo, cfo, cmo, cto, coo, meta).",
    "params": {"agent_id": "str", "reason": "str"},
    "returns": {"sent": "bool"},
}


async def run(ctx, agent_id: str, reason: str) -> dict:
    if agent_id in {"ceo", "cfo", "cmo", "cto", "coo", "meta"}:
        raise PermissionError(f"cannot fire executive: {agent_id}")
    await ctx.bus.publish("agent.fire_request", {"agent_id": agent_id, "reason": reason})
    return {"sent": True}
