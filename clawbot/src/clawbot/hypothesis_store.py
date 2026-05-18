"""Single source of truth for the company's currently-active strategic bet.

Exactly one row has status='active' at any time. set_active() supersedes the
previous active row. kill_active() marks the active row killed (no new active).
The board writes to this store; the CEO reads it as a strategic constraint."""
from __future__ import annotations

import json
import uuid
from typing import Any


class HypothesisStore:
    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def init_schema(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS active_hypothesis (
                    hypothesis_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    kill_criteria TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    killed_at TIMESTAMPTZ
                )
            """)
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_hypothesis_status ON active_hypothesis(status)"
            )

    async def set_active(self, *, name: str, description: str, kill_criteria: dict) -> str:
        new_id = uuid.uuid4().hex
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "UPDATE active_hypothesis SET status='superseded' WHERE status='active'"
                )
                await conn.execute(
                    "INSERT INTO active_hypothesis (hypothesis_id, name, description, kill_criteria, status) "
                    "VALUES ($1, $2, $3, $4, 'active')",
                    new_id, name, description, json.dumps(kill_criteria),
                )
        return new_id

    async def get_active(self) -> dict | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT hypothesis_id, name, description, kill_criteria, status, created_at "
                "FROM active_hypothesis WHERE status='active' LIMIT 1"
            )
        if row is None:
            return None
        return {
            "hypothesis_id": row["hypothesis_id"],
            "name": row["name"],
            "description": row["description"],
            "kill_criteria": json.loads(row["kill_criteria"]),
            "status": row["status"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        }

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
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE active_hypothesis SET status='killed', killed_at=NOW() "
                "WHERE status='active'"
            )
