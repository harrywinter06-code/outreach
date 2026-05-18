import math

META = {
    "name": "bandit_allocate_budget", "builtin": True,
    "description": "UCB1-based budget allocation across an experiment's arms (deterministic substitute for Thompson; AST scanner forbids `random`). Returns each arm's share of total_budget.",
    "params": {"experiment_id": "str", "total_budget": "float"},
    "returns": {"allocations": "dict", "scores": "dict"},
}


async def run(ctx, experiment_id: str, total_budget: float) -> dict:
    rows = await ctx.sql.query(
        "SELECT arm, "
        "       COUNT(*) AS trials, "
        "       SUM(CASE WHEN success THEN 1 ELSE 0 END) AS successes "
        "FROM experiment_observations WHERE experiment_id = $1 GROUP BY arm",
        experiment_id,
    )
    if not rows:
        return {"allocations": {}, "scores": {}}
    total_trials = sum(int(r["trials"]) for r in rows) or 1
    log_n = math.log(max(total_trials, 1))
    scores: dict[str, float] = {}
    for r in rows:
        arm = str(r["arm"])
        trials = max(int(r["trials"]), 1)
        successes = int(r["successes"] or 0)
        mean = successes / trials
        bonus = math.sqrt(2 * log_n / trials)
        scores[arm] = mean + bonus
    total_score = sum(scores.values()) or 1.0
    allocations = {arm: round(total_budget * s / total_score, 4) for arm, s in scores.items()}
    return {"allocations": allocations, "scores": {k: round(v, 4) for k, v in scores.items()}}
