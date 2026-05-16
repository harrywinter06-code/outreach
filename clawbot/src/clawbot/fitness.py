"""
Agent fitness scoring. Revenue is the primary signal — all proxy metrics are
secondary. Goodhart's Law countermeasure: if revenue is zero, proxy scores
cannot push fitness above 0.30 regardless of completion rate or efficiency.
"""
from dataclasses import dataclass
from pathlib import Path
import json


@dataclass
class FitnessScore:
    agent_id: str
    revenue_7d_gbp: float
    tasks_completed: int
    tasks_failed: int
    avg_latency_s: float
    score: float  # 0.0 – 1.0
    attributed_revenue_7d_gbp: float = 0.0
    attribution_rate: float = 0.0


def compute_fitness(
    agent_id: str,
    revenue_7d_gbp: float,
    tasks_completed: int,
    tasks_failed: int,
    avg_latency_s: float,
    latency_ceiling_s: float = 120.0,
    attributed_revenue_7d_gbp: float = 0.0,
    attribution_rate: float = 0.0,
) -> FitnessScore:
    total_tasks = tasks_completed + tasks_failed
    completion_rate = tasks_completed / total_tasks if total_tasks > 0 else 0.0

    # Efficiency is only meaningful when work was actually attempted. A do-nothing
    # agent (0 tasks, 0 latency) would otherwise score 1.0 efficiency for free and
    # accumulate a 0.15 fitness floor — beating agents that tried and failed. The
    # no-op tax below removes that perverse incentive.
    if total_tasks > 0:
        efficiency = max(0.0, 1.0 - (avg_latency_s / latency_ceiling_s))
    else:
        efficiency = 0.0

    # Revenue component: log-scaled, caps at 1.0 for £100+/week
    import math
    revenue_score = min(1.0, math.log1p(revenue_7d_gbp) / math.log1p(100.0))

    raw = (
        revenue_score * 0.60
        + completion_rate * 0.25
        + efficiency * 0.15
    )

    # No-op tax: an agent that performed zero work AND earned zero revenue scores 0.
    # Without this, do-nothing agents avoid the bottom-20% mutation queue while
    # peers that try are penalised for their failures.
    if total_tasks == 0 and revenue_7d_gbp == 0.0:
        raw = 0.0

    # Hard cap: no revenue → score cannot exceed 0.30 (Goodhart countermeasure)
    if revenue_7d_gbp == 0.0:
        raw = min(raw, 0.30)

    return FitnessScore(
        agent_id=agent_id,
        revenue_7d_gbp=revenue_7d_gbp,
        tasks_completed=tasks_completed,
        tasks_failed=tasks_failed,
        avg_latency_s=avg_latency_s,
        score=round(raw, 4),
        attributed_revenue_7d_gbp=attributed_revenue_7d_gbp,
        attribution_rate=attribution_rate,
    )


def load_fitness_from_metrics(metrics_dir: Path, agent_id: str) -> FitnessScore | None:
    """
    Load pre-computed fitness from /metrics/<agent_id>/fitness.json.
    Returns None if the file doesn't exist yet.
    """
    path = metrics_dir / agent_id / "fitness.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return FitnessScore(
        agent_id=data["agent_id"],
        revenue_7d_gbp=data["revenue_7d_gbp"],
        tasks_completed=data["tasks_completed"],
        tasks_failed=data["tasks_failed"],
        avg_latency_s=data["avg_latency_s"],
        score=data["score"],
        attributed_revenue_7d_gbp=data.get("attributed_revenue_7d_gbp", 0.0),
        attribution_rate=data.get("attribution_rate", 0.0),
    )


def save_fitness(metrics_dir: Path, fitness: FitnessScore) -> None:
    agent_dir = metrics_dir / fitness.agent_id
    agent_dir.mkdir(parents=True, exist_ok=True)
    path = agent_dir / "fitness.json"
    path.write_text(
        json.dumps(
            {
                "agent_id": fitness.agent_id,
                "revenue_7d_gbp": fitness.revenue_7d_gbp,
                "tasks_completed": fitness.tasks_completed,
                "tasks_failed": fitness.tasks_failed,
                "avg_latency_s": fitness.avg_latency_s,
                "score": fitness.score,
                "attributed_revenue_7d_gbp": fitness.attributed_revenue_7d_gbp,
                "attribution_rate": fitness.attribution_rate,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def bottom_percentile(
    scores: list[FitnessScore],
    pct: float = 0.20,
) -> list[FitnessScore]:
    """Return the bottom `pct` fraction of agents by fitness score."""
    ranked = sorted(scores, key=lambda s: s.score)
    cutoff = max(1, int(len(ranked) * pct))
    return ranked[:cutoff]
