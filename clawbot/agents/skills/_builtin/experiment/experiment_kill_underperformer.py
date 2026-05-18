META = {
    "name": "experiment_kill_underperformer", "builtin": True,
    "description": "Identify arms below a success-rate threshold (requires min_trials samples) and publish experiment.arm_killed events for downstream rotation drop.",
    "params": {"experiment_id": "str", "threshold": "float", "min_trials": "int"},
    "returns": {"killed_arms": "list", "kept_arms": "list"},
}


async def run(ctx, experiment_id: str, threshold: float = 0.05, min_trials: int = 30) -> dict:
    rows = await ctx.sql.query(
        "SELECT arm, "
        "       COUNT(*) AS trials, "
        "       SUM(CASE WHEN success THEN 1 ELSE 0 END) AS successes "
        "FROM experiment_observations WHERE experiment_id = $1 GROUP BY arm",
        experiment_id,
    )
    killed: list[str] = []
    kept: list[str] = []
    for r in rows:
        arm = str(r["arm"])
        trials = int(r["trials"])
        successes = int(r["successes"] or 0)
        if trials < min_trials:
            kept.append(arm)
            continue
        rate = successes / trials if trials else 0.0
        if rate < threshold:
            killed.append(arm)
            await ctx.bus.publish("experiment.arm_killed", {
                "experiment_id": experiment_id, "arm": arm,
                "trials": trials, "successes": successes, "rate": round(rate, 4),
            })
        else:
            kept.append(arm)
    return {"killed_arms": killed, "kept_arms": kept}
