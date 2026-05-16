"""
Mutation lineage tracker.

Every mutation produces a record. Records are stored as JSON files under
/metrics/lineage/<agent_id>/generation_<NNN>.json so they survive process restarts
and are inspectable without a database.

A lineage record captures: parent_sha (hash of the SOUL before mutation), child_sha
(after), fitness_before, the timestamp, and an excerpt of the new mutable section.
Over time, this is the *phylogeny* — it answers "which lineage of strategies
descended from H1, and did any of them outperform their ancestors?".
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, asdict
from datetime import datetime, UTC
from pathlib import Path


FITNESS_TREND_DEFAULT_WINDOW = 5      # generations to average over
FITNESS_TREND_UP_MULTIPLIER = 1.05    # ≥5% improvement counts as "up"
FITNESS_TREND_DOWN_MULTIPLIER = 0.95  # ≤5% drop counts as "down"


@dataclass(frozen=True)
class LineageRecord:
    agent_id: str
    generation: int
    parent_sha: str
    child_sha: str
    fitness_before: float
    timestamp: str
    mutation_excerpt: str  # first 240 chars of the new MUTABLE section


def soul_sha(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class LineageStore:
    """JSON-file-backed lineage history. One directory per agent, one file per generation."""

    def __init__(self, metrics_dir: Path) -> None:
        self._root = metrics_dir / "lineage"

    def _agent_dir(self, agent_id: str) -> Path:
        return self._root / agent_id

    def current_generation(self, agent_id: str) -> int:
        """Highest generation number recorded for this agent, or 0 if none."""
        d = self._agent_dir(agent_id)
        if not d.exists():
            return 0
        highest = 0
        for f in d.glob("generation_*.json"):
            try:
                n = int(f.stem.split("_")[1])
                if n > highest:
                    highest = n
            except (IndexError, ValueError):
                continue
        return highest

    def append(
        self,
        agent_id: str,
        parent_content: str,
        child_content: str,
        fitness_before: float,
        mutation_excerpt: str,
    ) -> LineageRecord:
        generation = self.current_generation(agent_id) + 1
        record = LineageRecord(
            agent_id=agent_id,
            generation=generation,
            parent_sha=soul_sha(parent_content),
            child_sha=soul_sha(child_content),
            fitness_before=fitness_before,
            timestamp=datetime.now(UTC).isoformat(),
            mutation_excerpt=mutation_excerpt[:240],
        )
        d = self._agent_dir(agent_id)
        d.mkdir(parents=True, exist_ok=True)
        (d / f"generation_{generation:03d}.json").write_text(
            json.dumps(asdict(record), indent=2), encoding="utf-8"
        )
        return record

    def history(self, agent_id: str) -> list[LineageRecord]:
        """All generations in order, oldest first."""
        d = self._agent_dir(agent_id)
        if not d.exists():
            return []
        records = []
        for f in sorted(d.glob("generation_*.json")):
            data = json.loads(f.read_text(encoding="utf-8"))
            records.append(LineageRecord(**data))
        return records

    def fitness_trend(self, agent_id: str, window: int = FITNESS_TREND_DEFAULT_WINDOW) -> str:
        """Are recent generations trending up, down, or flat by fitness_before?
        Useful for the homeostasis fence."""
        recs = self.history(agent_id)[-window:]
        if len(recs) < 2:
            return "insufficient_data"
        first, last = recs[0].fitness_before, recs[-1].fitness_before
        if last > first * FITNESS_TREND_UP_MULTIPLIER:
            return "up"
        if last < first * FITNESS_TREND_DOWN_MULTIPLIER:
            return "down"
        return "flat"
