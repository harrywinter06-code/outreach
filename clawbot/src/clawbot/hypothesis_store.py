"""Multi-hypothesis portfolio store.

Up to N hypotheses can be active simultaneously, where N = max_active.
Resource-allocation hint is the `weight` column (0.0-1.0, agents read it
when prioritising attention). `progress_score` is computed externally by
the auto-diversification loop and read by it next cycle to decide whether
to spawn a replacement."""
from __future__ import annotations

import json
import uuid
from typing import Any


class HypothesisStore:
    def __init__(self, pool: Any, max_active: int = 3) -> None:
        self._pool = pool
        self._max_active = max_active

    async def init_schema(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS active_hypothesis (
                    hypothesis_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    kill_criteria TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    weight NUMERIC(4, 3) NOT NULL DEFAULT 1.0,
                    progress_score NUMERIC(4, 3) NOT NULL DEFAULT 0.0,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    killed_at TIMESTAMPTZ
                )
            """)
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_hypothesis_status ON active_hypothesis(status)"
            )

    async def add_hypothesis(
        self, *, name: str, description: str, kill_criteria: dict,
        weight: float = 1.0,
    ) -> str:
        """Append a new active hypothesis. Raises RuntimeError if the portfolio
        is already at MAX_ACTIVE_HYPOTHESES. To replace an existing entry, call
        kill_hypothesis_by_id first."""
        async with self._pool.acquire() as conn:
            count_row = await conn.fetchrow(
                "SELECT COUNT(*) AS n FROM active_hypothesis WHERE status='active'"
            )
            current = int(count_row["n"]) if count_row else 0
            if current >= self._max_active:
                raise RuntimeError(
                    f"portfolio_full: {current} active hypotheses, cap is {self._max_active}. "
                    f"Kill one before adding another."
                )
            new_id = uuid.uuid4().hex
            await conn.execute(
                "INSERT INTO active_hypothesis (hypothesis_id, name, description, "
                "kill_criteria, status, weight) VALUES ($1, $2, $3, $4, 'active', $5)",
                new_id, name, description, json.dumps(kill_criteria), float(weight),
            )
        return new_id

    async def set_active(self, *, name: str, description: str, kill_criteria: dict) -> str:
        """Backwards-compat: single-active behaviour. Kills any existing active
        rows then adds this one with weight=1.0. Used by the H1 seed and any
        legacy caller. New code should use add_hypothesis."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE active_hypothesis SET status='superseded', killed_at=NOW() "
                "WHERE status='active'"
            )
        return await self.add_hypothesis(
            name=name, description=description, kill_criteria=kill_criteria, weight=1.0,
        )

    async def get_active(self) -> dict | None:
        """Backwards-compat: returns the single highest-weight active hypothesis."""
        portfolio = await self.get_active_portfolio()
        if not portfolio:
            return None
        return max(portfolio, key=lambda h: float(h["weight"]))

    async def get_active_portfolio(self) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT hypothesis_id, name, description, kill_criteria, status, "
                "weight, progress_score, created_at FROM active_hypothesis "
                "WHERE status='active' ORDER BY weight DESC, created_at ASC"
            )
        return [
            {
                "hypothesis_id": r["hypothesis_id"],
                "name": r["name"],
                "description": r["description"],
                "kill_criteria": json.loads(r["kill_criteria"]),
                "status": r["status"],
                "weight": float(r["weight"]),
                "progress_score": float(r["progress_score"]),
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ]

    async def list_history(self) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT hypothesis_id, name, description, status, created_at, killed_at "
                "FROM active_hypothesis ORDER BY created_at DESC"
            )
        return [
            {"hypothesis_id": r["hypothesis_id"], "name": r["name"],
             "description": r["description"], "status": r["status"]}
            for r in rows
        ]

    async def kill_active(self, *, reason: str) -> None:
        """Backwards-compat: kills ALL active hypotheses. New code should use
        kill_hypothesis_by_id to kill exactly one."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE active_hypothesis SET status='killed', killed_at=NOW() "
                "WHERE status='active'"
            )

    async def kill_hypothesis_by_id(self, *, hypothesis_id: str, reason: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE active_hypothesis SET status='killed', killed_at=NOW() "
                "WHERE hypothesis_id=$1 AND status='active'",
                hypothesis_id,
            )

    async def update_progress_score(self, *, hypothesis_id: str, score: float) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE active_hypothesis SET progress_score=$1 "
                "WHERE hypothesis_id=$2 AND status='active'",
                float(score), hypothesis_id,
            )
