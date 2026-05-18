"""
asyncpg connection pool + pgvector schema init.
Only this module knows the knowledge table schema.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import asyncpg

if TYPE_CHECKING:
    pass


class Database:
    def __init__(self, database_url: str) -> None:
        self._url = database_url
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        from pgvector.asyncpg import register_vector

        async def _init(conn: asyncpg.Connection) -> None:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            await register_vector(conn)

        self._pool = await asyncpg.create_pool(
            self._url,
            min_size=2,
            max_size=20,  # raised from 10 — see Audit D #10
            init=_init,
        )

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None

    @property
    def pool(self) -> asyncpg.Pool:
        assert self._pool is not None, "call connect() first"
        return self._pool

    async def init_schema(self) -> None:
        """Idempotent — safe to call on every startup."""
        assert self._pool is not None, "call connect() first"
        await self._pool.execute("CREATE EXTENSION IF NOT EXISTS vector")
        await self._pool.execute("""
            CREATE TABLE IF NOT EXISTS knowledge (
                id         SERIAL PRIMARY KEY,
                content    TEXT        NOT NULL,
                embedding  vector(384),
                category   TEXT        NOT NULL DEFAULT '',
                metadata   JSONB       NOT NULL DEFAULT '{}',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        # hnsw index works on empty tables; ivfflat does not
        await self._pool.execute("""
            CREATE INDEX IF NOT EXISTS knowledge_hnsw_idx
            ON knowledge USING hnsw (embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 64)
        """)
        await self._pool.execute("""
            CREATE INDEX IF NOT EXISTS knowledge_category_idx
            ON knowledge (category)
        """)
        await self._pool.execute("""
            CREATE TABLE IF NOT EXISTS causal_chain (
                event_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                chain_id    UUID NOT NULL,
                agent_id    TEXT NOT NULL,
                action_type TEXT NOT NULL,
                causal_depth INTEGER NOT NULL DEFAULT 0,
                ts          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                attributed_revenue_gbp FLOAT NOT NULL DEFAULT 0.0,
                confidence  FLOAT NOT NULL DEFAULT 0.0,
                closed_at   TIMESTAMPTZ,
                metadata    JSONB NOT NULL DEFAULT '{}'
            )
        """)
        await self._pool.execute("""
            CREATE INDEX IF NOT EXISTS causal_chain_agent_ts_idx
            ON causal_chain (agent_id, ts)
        """)
        await self._pool.execute("""
            CREATE INDEX IF NOT EXISTS causal_chain_chain_id_idx
            ON causal_chain (chain_id)
        """)
        await self._pool.execute("""
            CREATE TABLE IF NOT EXISTS product_causal_map (
                gumroad_product_id TEXT PRIMARY KEY,
                chain_id           UUID NOT NULL,
                product_title      TEXT NOT NULL DEFAULT '',
                registered_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await self._pool.execute("""
            CREATE TABLE IF NOT EXISTS skill_calls (
                id          BIGSERIAL PRIMARY KEY,
                skill_name  TEXT NOT NULL,
                caller_id   TEXT NOT NULL,
                ok          BOOLEAN NOT NULL,
                cost_usd    DOUBLE PRECISION NOT NULL DEFAULT 0,
                latency_ms  INT NOT NULL DEFAULT 0,
                error       TEXT,
                called_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await self._pool.execute("""
            CREATE INDEX IF NOT EXISTS idx_skill_calls_name_time
            ON skill_calls (skill_name, called_at DESC)
        """)
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
            # Multi-hypothesis portfolio columns (added 2026-05-18)
            await conn.execute("""
                ALTER TABLE active_hypothesis
                ADD COLUMN IF NOT EXISTS weight NUMERIC(4, 3) NOT NULL DEFAULT 1.0
            """)
            await conn.execute("""
                ALTER TABLE active_hypothesis
                ADD COLUMN IF NOT EXISTS progress_score NUMERIC(4, 3) NOT NULL DEFAULT 0.0
            """)
            await conn.execute("""
                ALTER TABLE plans
                ADD COLUMN IF NOT EXISTS hypothesis_id TEXT
            """)
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_plans_hypothesis "
                "ON plans(hypothesis_id) WHERE hypothesis_id IS NOT NULL"
            )
        # Phase H Task 29 — outreach + CRM
        async with self._pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS leads (
                    email       TEXT PRIMARY KEY,
                    name        TEXT NOT NULL DEFAULT '',
                    company     TEXT NOT NULL DEFAULT '',
                    title       TEXT NOT NULL DEFAULT '',
                    source      TEXT NOT NULL DEFAULT '',
                    stage       TEXT NOT NULL DEFAULT 'new',
                    score       DOUBLE PRECISION NOT NULL DEFAULT 0.0,
                    metadata    JSONB NOT NULL DEFAULT '{}',
                    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_leads_stage ON leads(stage)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_leads_company ON leads(company)"
            )
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS suppression (
                    email          TEXT PRIMARY KEY,
                    reason         TEXT NOT NULL DEFAULT '',
                    suppressed_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
        # Phase H Session B — experiments
        async with self._pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS experiments (
                    id TEXT PRIMARY KEY,
                    hypothesis TEXT NOT NULL,
                    metric TEXT NOT NULL,
                    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    cutoff_at TIMESTAMPTZ
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS experiment_observations (
                    id BIGSERIAL PRIMARY KEY,
                    experiment_id TEXT NOT NULL REFERENCES experiments(id),
                    arm TEXT NOT NULL,
                    success BOOLEAN NOT NULL,
                    observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_experiment_observations_exp_arm "
                "ON experiment_observations (experiment_id, arm)"
            )
        # Phase H Task 36 — support tickets
        async with self._pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS tickets (
                    id TEXT PRIMARY KEY,
                    subject TEXT NOT NULL,
                    body TEXT NOT NULL,
                    assigned_to TEXT,
                    status TEXT NOT NULL DEFAULT 'open',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tickets_status_updated "
                "ON tickets (status, updated_at DESC)"
            )
        # Portfolio operator Task 1 — capital ledger
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
        # Portfolio operator Task 4 — company fitness snapshots
        async with self._pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS company_fitness_snapshots (
                    snapshot_id BIGSERIAL PRIMARY KEY,
                    snapshot_date DATE NOT NULL UNIQUE,
                    score NUMERIC(4, 3) NOT NULL,
                    revenue_7d_gbp NUMERIC(12, 2) NOT NULL,
                    plans_active INTEGER NOT NULL,
                    plans_advanced_7d INTEGER NOT NULL,
                    plans_pivoted_7d INTEGER NOT NULL,
                    capital_deployed_7d_gbp NUMERIC(12, 2) NOT NULL,
                    skill_calls_7d INTEGER NOT NULL,
                    skill_call_success_rate NUMERIC(4, 3) NOT NULL,
                    breakdown TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
