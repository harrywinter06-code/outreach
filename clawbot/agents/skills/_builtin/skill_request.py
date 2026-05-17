META = {
    "name": "skill_request", "builtin": True,
    "description": "Request a new skill. SkillForge will draft, validate, shadow, and promote.",
    "params": {
        "name": "str", "description": "str",
        "params_schema": "dict", "returns_schema": "dict",
        "example_call": "dict",
    },
    "returns": {"queued": "bool"},
}


async def run(ctx, name: str, description: str, params_schema: dict,
              returns_schema: dict, example_call: dict) -> dict:
    await ctx.bus.publish("skill.request", {
        "name": name, "description": description,
        "params_schema": params_schema, "returns_schema": returns_schema,
        "example_call": example_call, "requested_by": ctx.caller_id,
    })
    return {"queued": True}
