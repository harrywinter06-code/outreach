"""Capital ledger — records every spend authorization with linkable provenance.

The ledger is the enforcement substrate for daily/weekly caps. _LivePayments
queries `current_period_total_gbp` before any Stripe call that could trigger
spend, and raises if a new authorization would exceed the cap. This is
independent of Stripe's own server-side spending_controls — defence in depth."""
from __future__ import annotations

import json
from decimal import Decimal
from typing import Any


class CapitalLedger:
    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def init_schema(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS capital_ledger (
                    entry_id BIGSERIAL PRIMARY KEY,
                    skill_call_id BIGINT,
                    agent_id TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    amount_gbp NUMERIC(12, 2) NOT NULL,
                    currency_original TEXT NOT NULL DEFAULT 'GBP',
                    amount_original NUMERIC(12, 2),
                    stripe_object_id TEXT,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    is_live_mode BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_capital_ledger_created "
                "ON capital_ledger(created_at DESC)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_capital_ledger_agent "
                "ON capital_ledger(agent_id, created_at DESC)"
            )

    async def record(
        self, *, agent_id: str, action_type: str, amount_gbp: Decimal,
        is_live_mode: bool = False,
        stripe_object_id: str | None = None,
        metadata: dict | None = None,
        currency_original: str = "GBP",
        amount_original: Decimal | None = None,
        skill_call_id: int | None = None,
    ) -> int:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO capital_ledger (skill_call_id, agent_id, action_type, amount_gbp, "
                "currency_original, amount_original, stripe_object_id, metadata, is_live_mode) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) RETURNING entry_id",
                skill_call_id, agent_id, action_type, amount_gbp,
                currency_original, amount_original, stripe_object_id,
                json.dumps(metadata or {}), is_live_mode,
            )
        return int(row["entry_id"])

    async def current_period_total_gbp(
        self, *, period_hours: int, live_only: bool = True,
    ) -> Decimal:
        """Sum of amounts in the trailing `period_hours` window. Refunds are
        negative entries; the sum is net spend."""
        async with self._pool.acquire() as conn:
            if live_only:
                row = await conn.fetchrow(
                    "SELECT COALESCE(SUM(amount_gbp), 0) AS total "
                    "FROM capital_ledger "
                    "WHERE created_at > NOW() - ($1 || ' hours')::INTERVAL "
                    "AND is_live_mode = TRUE",
                    str(period_hours),
                )
            else:
                row = await conn.fetchrow(
                    "SELECT COALESCE(SUM(amount_gbp), 0) AS total "
                    "FROM capital_ledger "
                    "WHERE created_at > NOW() - ($1 || ' hours')::INTERVAL",
                    str(period_hours),
                )
        return Decimal(str(row["total"])) if row else Decimal("0")

    async def list_recent(self, *, limit: int = 50) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT entry_id, agent_id, action_type, amount_gbp, "
                "stripe_object_id, is_live_mode, created_at "
                "FROM capital_ledger ORDER BY created_at DESC LIMIT $1",
                limit,
            )
        return [dict(r) for r in rows]
