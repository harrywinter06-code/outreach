META = {
    "name": "bus_publish", "builtin": True,
    "description": "Publish to a non-protected bus topic. Use for inter-agent coordination.",
    "params": {"topic": "str", "payload": "dict"},
    "returns": {"msg_id": "str"},
}


async def run(ctx, topic: str, payload: dict) -> dict:
    return {"msg_id": await ctx.bus.publish(topic, payload)}
