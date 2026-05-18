META = {
    "name": "experiment_summarize", "builtin": True,
    "description": "LLM-narrative summary of an experiment's arm-level results. Returns a short verdict + per-arm stats.",
    "params": {"experiment_id": "str"},
    "returns": {"summary": "str", "arms": "list"},
    "cost_estimate_usd": 0.002,
}


async def run(ctx, experiment_id: str) -> dict:
    exp_rows = await ctx.sql.query(
        "SELECT hypothesis, metric FROM experiments WHERE id = $1",
        experiment_id,
    )
    hypothesis = exp_rows[0]["hypothesis"] if exp_rows else ""
    metric = exp_rows[0]["metric"] if exp_rows else ""

    obs_rows = await ctx.sql.query(
        "SELECT arm, "
        "       COUNT(*) AS trials, "
        "       SUM(CASE WHEN success THEN 1 ELSE 0 END) AS successes "
        "FROM experiment_observations WHERE experiment_id = $1 GROUP BY arm",
        experiment_id,
    )
    arms = []
    for r in obs_rows:
        trials = int(r["trials"])
        successes = int(r["successes"] or 0)
        arms.append({
            "arm": str(r["arm"]),
            "trials": trials,
            "successes": successes,
            "rate": round(successes / trials, 4) if trials else 0.0,
        })

    if not arms:
        return {"summary": "no observations yet", "arms": []}

    arms_str = "\n".join(
        f"- {a['arm']}: {a['successes']}/{a['trials']} ({a['rate']:.2%})" for a in arms
    )
    user = (
        f"Experiment hypothesis: {hypothesis}\n"
        f"Metric: {metric}\n"
        f"Arm results:\n{arms_str}\n\n"
        f"Write a 2-3 sentence verdict: which arm is winning, by how much, "
        f"and what the next action should be."
    )
    summary = await ctx.llm.complete(
        system="You are a quantitative experiment analyst. Be terse and decisive.",
        user=user,
        tier="worker",
    )
    return {"summary": summary, "arms": arms}
