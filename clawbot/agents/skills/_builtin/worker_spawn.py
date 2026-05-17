import uuid

META = {
    "name": "worker_spawn", "builtin": True,
    "description": "Spawn a new worker agent. Caller authors the SOUL text. Returns agent_id.",
    "params": {"role": "str", "soul_text": "str", "supervisor": "str", "call_interval_s": "int"},
    "returns": {"agent_id": "str"},
}


async def run(ctx, role: str, soul_text: str, supervisor: str, call_interval_s: int = 600) -> dict:
    agent_id = f"{role}-{uuid.uuid4().hex[:8]}"
    await ctx.bus.publish("agent.spawn_request", {
        "agent_id": agent_id, "role": role, "soul_text": soul_text,
        "supervisor": supervisor, "call_interval_s": call_interval_s,
    })
    return {"agent_id": agent_id}
