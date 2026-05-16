"""
Fitness writer — turns observation logs into per-agent fitness.json.

Without this module, evolution.py's `_load_all_fitness` always returns []
(no fitness.json files exist), and the evolution loop never has data to evolve
against. The system is structurally evolution-capable but practically inert
until observations flow.

Observations are written by the scheduler at each agent cycle as JSONL lines
in /metrics/<agent_id>/observations.jsonl:
    {"ts": <unix>, "duration_s": <float>, "success": <bool>, "kind": "executive_cycle"}

The writer reads the last 7 days of observations per agent, aggregates them
into a FitnessScore, and writes /metrics/<agent_id>/fitness.json — the file
evolution.py looks for.

Revenue attribution: Gumroad gives a single company total, not per-agent.
We attribute equal share to all agents that produced at least one observation
in the window. The CEO and CMO have roughly equal "credit" for a sale that
neither directly executed — coarse, but consistent.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from clawbot.fitness import FitnessScore, compute_fitness, save_fitness

if TYPE_CHECKING:
    from clawbot.causal_store import CausalStore

logger = logging.getLogger(__name__)

FITNESS_WINDOW_S = 7 * 86_400


@dataclass(frozen=True)
class Observation:
    ts: float
    duration_s: float
    success: bool
    kind: str


def append_observation(
    metrics_dir: Path,
    agent_id: str,
    duration_s: float,
    success: bool,
    kind: str = "cycle",
) -> None:
    """Append one observation line for an agent. Cheap — called per cycle."""
    agent_dir = metrics_dir / agent_id
    agent_dir.mkdir(parents=True, exist_ok=True)
    line = json.dumps({
        "ts": time.time(),
        "duration_s": float(duration_s),
        "success": bool(success),
        "kind": kind,
    })
    with (agent_dir / "observations.jsonl").open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def read_recent_observations(
    metrics_dir: Path,
    agent_id: str,
    window_s: float = FITNESS_WINDOW_S,
) -> list[Observation]:
    """Read observations within the rolling window. Skips malformed lines silently."""
    path = metrics_dir / agent_id / "observations.jsonl"
    if not path.exists():
        return []
    cutoff = time.time() - window_s
    out: list[Observation] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            data = json.loads(line)
            ts = float(data["ts"])
            if ts < cutoff:
                continue
            out.append(Observation(
                ts=ts,
                duration_s=float(data.get("duration_s", 0.0)),
                success=bool(data.get("success", False)),
                kind=str(data.get("kind", "cycle")),
            ))
        except (json.JSONDecodeError, KeyError, ValueError, TypeError):
            continue
    return out


def trim_observations(
    metrics_dir: Path,
    agent_id: str,
    window_s: float = FITNESS_WINDOW_S,
) -> int:
    """Rewrite observations.jsonl keeping only entries within the window.
    Returns number of entries kept. Prevents unbounded file growth."""
    path = metrics_dir / agent_id / "observations.jsonl"
    if not path.exists():
        return 0
    cutoff = time.time() - window_s
    kept: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            ts = float(json.loads(line)["ts"])
            if ts >= cutoff:
                kept.append(line)
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
    path.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
    return len(kept)


def compute_and_save_fitness(
    metrics_dir: Path,
    agent_id: str,
    revenue_share_gbp: float,
    attributed_revenue_7d_gbp: float = 0.0,
    attribution_rate: float = 0.0,
) -> FitnessScore | None:
    """Build FitnessScore from observation window and revenue share. Persist to fitness.json."""
    obs = read_recent_observations(metrics_dir, agent_id)
    if not obs:
        return None
    tasks_completed = sum(1 for o in obs if o.success)
    tasks_failed = sum(1 for o in obs if not o.success)
    avg_latency = sum(o.duration_s for o in obs) / max(1, len(obs))

    score = compute_fitness(
        agent_id=agent_id,
        revenue_7d_gbp=revenue_share_gbp,
        tasks_completed=tasks_completed,
        tasks_failed=tasks_failed,
        avg_latency_s=avg_latency,
        attributed_revenue_7d_gbp=attributed_revenue_7d_gbp,
        attribution_rate=attribution_rate,
    )
    save_fitness(metrics_dir, score)
    return score


def list_active_agents(metrics_dir: Path) -> list[str]:
    """Every agent_id with an observations.jsonl file (regardless of staleness)."""
    if not metrics_dir.exists():
        return []
    out = []
    for d in metrics_dir.iterdir():
        if d.is_dir() and (d / "observations.jsonl").exists():
            out.append(d.name)
    return out


async def refresh_all_fitness(
    metrics_dir: Path,
    total_revenue_7d_gbp: float,
    causal_store: "CausalStore | None" = None,
) -> dict[str, FitnessScore | None]:
    """Recompute fitness.json for every agent with observations.

    Revenue attribution: if a CausalStore is provided, per-agent attributed
    revenue is fetched from it. Otherwise, equal share among agents that
    produced at least one observation in the window.
    """
    agents = list_active_agents(metrics_dir)
    active_with_obs = []
    for agent_id in agents:
        if read_recent_observations(metrics_dir, agent_id):
            active_with_obs.append(agent_id)
            trim_observations(metrics_dir, agent_id)
    if not active_with_obs:
        return {}
    results: dict[str, FitnessScore | None] = {}
    if causal_store is not None:
        for agent_id in active_with_obs:
            attributed = await causal_store.attributed_revenue_7d(agent_id)
            rate = await causal_store.attribution_rate(agent_id)
            results[agent_id] = compute_and_save_fitness(
                metrics_dir, agent_id,
                revenue_share_gbp=total_revenue_7d_gbp / len(active_with_obs),
                attributed_revenue_7d_gbp=attributed,
                attribution_rate=rate,
            )
    else:
        share = total_revenue_7d_gbp / len(active_with_obs)
        for agent_id in active_with_obs:
            results[agent_id] = compute_and_save_fitness(metrics_dir, agent_id, share)
    return results
