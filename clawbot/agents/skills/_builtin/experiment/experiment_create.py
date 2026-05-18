import uuid

META = {
    "name": "experiment_create", "builtin": True,
    "description": "Register a new experiment. Returns an experiment_id used by record/summarize/kill.",
    "params": {"hypothesis": "str", "metric": "str", "cutoff_at": "str"},
    "returns": {"experiment_id": "str", "hypothesis": "str"},
}


async def run(ctx, hypothesis: str, metric: str, cutoff_at: str = "") -> dict:
    exp_id = f"exp_{uuid.uuid4().hex[:12]}"
    if cutoff_at:
        await ctx.sql.query(
            "INSERT INTO experiments (id, hypothesis, metric, cutoff_at) "
            "VALUES ($1, $2, $3, $4::timestamptz)",
            exp_id, hypothesis, metric, cutoff_at,
        )
    else:
        await ctx.sql.query(
            "INSERT INTO experiments (id, hypothesis, metric) VALUES ($1, $2, $3)",
            exp_id, hypothesis, metric,
        )
    return {"experiment_id": exp_id, "hypothesis": hypothesis}
