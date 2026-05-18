"""Async CRUD over the plans table.

Plans persist multi-cycle commitments per executive. The current milestone is
the lowest-indexed `status='active'` row for the agent. Advancing closes the
current milestone (status='done') and unblocks the next one; pivoting closes
the entire current plan (status='pivoted') and creates a new plan_id chain."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MilestoneRow:
    plan_id: str
    agent_id: str
    milestone_idx: int
    hypothesis: str
    success_criteria: str  # JSON
    evidence: str          # JSON
    status: str


class PlanStore:
    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def init_schema(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS plans (
                    plan_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    milestone_idx INTEGER NOT NULL,
                    hypothesis TEXT NOT NULL,
                    success_criteria TEXT NOT NULL,
                    evidence TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (agent_id, plan_id, milestone_idx)
                )
            """)
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_plans_agent_status "
                "ON plans(agent_id, status, milestone_idx)"
            )

    async def create_plan(
        self, *, agent_id: str, hypothesis: str, milestones: list[dict],
        hypothesis_id: str | None = None,
    ) -> str:
        """Create a fresh plan chain. Returns the new plan_id.

        Each milestone is `{"hypothesis": str, "success_criteria": list[str]}`.
        The first milestone is marked active; subsequent ones are pending."""
        plan_id = uuid.uuid4().hex
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                for idx, m in enumerate(milestones):
                    status = "active" if idx == 0 else "pending"
                    await conn.execute(
                        "INSERT INTO plans (plan_id, agent_id, milestone_idx, hypothesis, "
                        "hypothesis_id, success_criteria, evidence, status) "
                        "VALUES ($1, $2, $3, $4, $5, $6, '[]', $7)",
                        plan_id, agent_id, idx, m["hypothesis"], hypothesis_id,
                        json.dumps(m["success_criteria"]), status,
                    )
        return plan_id

    async def get_current_milestone(self, *, agent_id: str) -> MilestoneRow | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT plan_id, agent_id, milestone_idx, hypothesis, success_criteria, "
                "evidence, status FROM plans WHERE agent_id=$1 AND status='active' "
                "ORDER BY milestone_idx ASC LIMIT 1",
                agent_id,
            )
        if row is None:
            return None
        return MilestoneRow(**dict(row))

    async def advance_milestone(self, *, agent_id: str) -> bool:
        """Close current milestone, activate next pending one. Returns True if
        a next milestone was activated, False if the plan is now complete."""
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                current = await conn.fetchrow(
                    "SELECT plan_id, milestone_idx FROM plans WHERE agent_id=$1 "
                    "AND status='active' ORDER BY milestone_idx ASC LIMIT 1 FOR UPDATE",
                    agent_id,
                )
                if current is None:
                    return False
                await conn.execute(
                    "UPDATE plans SET status='done', updated_at=NOW() "
                    "WHERE agent_id=$1 AND plan_id=$2 AND milestone_idx=$3",
                    agent_id, current["plan_id"], current["milestone_idx"],
                )
                next_row = await conn.fetchrow(
                    "SELECT milestone_idx FROM plans WHERE agent_id=$1 AND plan_id=$2 "
                    "AND status='pending' ORDER BY milestone_idx ASC LIMIT 1 FOR UPDATE",
                    agent_id, current["plan_id"],
                )
                if next_row is None:
                    return False
                await conn.execute(
                    "UPDATE plans SET status='active', updated_at=NOW() "
                    "WHERE agent_id=$1 AND plan_id=$2 AND milestone_idx=$3",
                    agent_id, current["plan_id"], next_row["milestone_idx"],
                )
        return True

    async def add_evidence(self, *, agent_id: str, item: dict) -> None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                current = await conn.fetchrow(
                    "SELECT plan_id, milestone_idx, evidence FROM plans "
                    "WHERE agent_id=$1 AND status='active' ORDER BY milestone_idx ASC LIMIT 1 FOR UPDATE",
                    agent_id,
                )
                if current is None:
                    return
                items = json.loads(current["evidence"])
                items.append(item)
                await conn.execute(
                    "UPDATE plans SET evidence=$1, updated_at=NOW() "
                    "WHERE agent_id=$2 AND plan_id=$3 AND milestone_idx=$4",
                    json.dumps(items), agent_id, current["plan_id"], current["milestone_idx"],
                )

    async def pivot(
        self, *, agent_id: str, reason: str,
        new_hypothesis: str, new_milestones: list[dict],
    ) -> str:
        """Mark all of the agent's current-plan rows as pivoted; create a new plan."""
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                current = await conn.fetchrow(
                    "SELECT plan_id FROM plans WHERE agent_id=$1 AND status IN ('active','pending') "
                    "ORDER BY milestone_idx ASC LIMIT 1 FOR UPDATE",
                    agent_id,
                )
                if current is not None:
                    await conn.execute(
                        "UPDATE plans SET status='pivoted', updated_at=NOW() "
                        "WHERE agent_id=$1 AND plan_id=$2",
                        agent_id, current["plan_id"],
                    )
        return await self.create_plan(
            agent_id=agent_id, hypothesis=new_hypothesis, milestones=new_milestones,
        )

    async def abandon_plans_for_hypothesis(self, *, hypothesis_id: str, reason: str) -> int:
        """When a hypothesis is killed, mark all its plans as abandoned.

        Returns the number of plan rows updated. The `reason` is currently not
        persisted (no plans.notes column); it appears in logs only.

        Note: kill_hypothesis_by_id in HypothesisStore cascades this automatically
        inside a single transaction. This method remains callable for explicit use."""
        async with self._pool.acquire() as conn:
            # Use RETURNING to count rows directly — more robust than parsing
            # asyncpg's command status string format.
            rows = await conn.fetch(
                "UPDATE plans SET status='abandoned', updated_at=NOW() "
                "WHERE hypothesis_id=$1 AND status IN ('active', 'pending') "
                "RETURNING plan_id",
                hypothesis_id,
            )
        return len(rows)
