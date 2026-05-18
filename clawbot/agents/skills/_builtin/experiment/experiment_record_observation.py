META = {
    "name": "experiment_record_observation", "builtin": True,
    "description": "Append a single (arm, success) observation to an experiment.",
    "params": {"experiment_id": "str", "arm": "str", "success": "bool"},
    "returns": {"experiment_id": "str", "arm": "str", "success": "bool"},
}


async def run(ctx, experiment_id: str, arm: str, success: bool) -> dict:
    await ctx.sql.query(
        "INSERT INTO experiment_observations (experiment_id, arm, success) "
        "VALUES ($1, $2, $3)",
        experiment_id, arm, success,
    )
    return {"experiment_id": experiment_id, "arm": arm, "success": success}
