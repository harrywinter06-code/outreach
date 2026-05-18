import math

META = {
    "name": "experiment_compute_significance", "builtin": True,
    "description": "Two-proportion z-test. Returns p-value and direction. Use to decide if A beats B significantly.",
    "params": {"a_successes": "int", "a_trials": "int", "b_successes": "int", "b_trials": "int"},
    "returns": {"p_value": "float", "winner": "str", "lift": "float"},
}


async def run(ctx, a_successes: int, a_trials: int, b_successes: int, b_trials: int) -> dict:
    if min(a_trials, b_trials) == 0:
        return {"p_value": 1.0, "winner": "none", "lift": 0.0}
    pa = a_successes / a_trials
    pb = b_successes / b_trials
    p_pool = (a_successes + b_successes) / (a_trials + b_trials)
    se = math.sqrt(p_pool * (1 - p_pool) * (1 / a_trials + 1 / b_trials))
    if se == 0:
        return {"p_value": 1.0, "winner": "none", "lift": 0.0}
    z = (pa - pb) / se
    p = 2 * (1 - _phi(abs(z)))
    winner = "A" if pa > pb else "B" if pb > pa else "tie"
    lift = (pa - pb) / pb if pb > 0 else 0.0
    return {"p_value": round(p, 4), "winner": winner, "lift": round(lift, 4)}


def _phi(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))
