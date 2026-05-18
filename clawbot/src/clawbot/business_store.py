"""
Swarm Phase Z1 — `business` is the unit of selection in the evolutionary
substrate. A business owns a niche, a genome (price + channel mix + copy
style + fulfilment template), a budget, and a revenue stream. The meta-
evaluator spawns/mutates/kills these against the measured £-fitness
signal.

This module owns CRUD over `businesses`, `business_revenue`,
`business_assets`, and `business_templates` — wired through asyncpg.
Spawn/cull/allocate loops live in scheduler.py (Phase Z2); this module
provides the primitives those loops compose.

Wire of responsibility (kept narrow on purpose):
- BusinessStore: row-level CRUD, fitness recompute, atomic spawn/kill
- (Z2) SwarmController: continuous spawn/kill loop, capital allocator
- (Z3) AssetPool: asset lifecycle (acquire/lend/reclaim)
- (Z4) TemplatePool: genome graduation + sampling with mutation

Free-tier LLM constraint: cap concurrent active businesses at
`MAX_ACTIVE_BUSINESSES` (default 8). Selection pressure compounds via
template inheritance, not breadth.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator


# Constant key for the swarm-spawn advisory lock. Picked from /dev/urandom
# once and frozen — must never change, must not collide with any other
# advisory lock in the codebase.
_SPAWN_LOCK_KEY = 0x53574152_4D5F5350  # "SWAR_SP"


class Genome(BaseModel):
    """Validated business genome. The unit of mutation in Z4.

    Red-team #2: free-form JSONB is a footgun — LLM mutations will produce
    invalid shapes ("price_gbp": "free", "channels": "twitter"). Validating
    at spawn AND mutation catches this before downstream skill code crashes.

    All fields except niche_question + price_gbp have safe defaults so
    minimal genomes from early templates still validate.
    """
    niche_question: str = Field(min_length=4, max_length=300)
    price_gbp: float = Field(gt=0.0, le=500.0)
    channels: list[str] = Field(default_factory=list, max_length=20)
    copy_voice: str = Field(default="plain", max_length=80)
    fulfilment_template: str = Field(default="default_v1", max_length=80)
    target_audience: str = Field(default="uk_adult", max_length=120)
    extra: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}  # tolerate forward-compat fields

    @field_validator("channels")
    @classmethod
    def _channels_lowercase_snake(cls, v: list[str]) -> list[str]:
        for c in v:
            if not isinstance(c, str) or not c or not c.replace("_", "").isalnum():
                raise ValueError(f"channel '{c}' must be lowercase_snake_case alphanumeric")
        return [c.lower() for c in v]


def validate_genome(raw: dict[str, Any]) -> dict[str, Any]:
    """Validate + normalise a genome dict. Raises ValueError on bad shape."""
    try:
        return Genome(**raw).model_dump()
    except ValidationError as exc:
        raise ValueError(f"invalid genome: {exc}") from exc


@dataclass(frozen=True)
class Business:
    business_id: str
    name: str
    niche: str
    genome: dict[str, Any]
    status: str  # 'active', 'killed', 'graduated'
    parent_id: str | None
    template_id: str | None
    budget_remaining_gbp: float
    revenue_total_gbp: float
    fitness_score: float
    spawned_at: datetime
    last_cycle_at: datetime | None
    killed_at: datetime | None
    kill_reason: str | None
    metadata: dict[str, Any]


@dataclass(frozen=True)
class BusinessTemplate:
    template_id: str
    source_business_id: str
    genome: dict[str, Any]
    revenue_at_graduation_gbp: float
    times_sampled: int
    times_produced_revenue: int


class BusinessStore:
    """Async CRUD over the `businesses` family of tables.

    All writes are atomic at the row level. Multi-row invariants (e.g.
    'at most N active businesses') are enforced via SELECT FOR UPDATE in
    spawn_business() — the spawn loop is single-writer per process.
    """

    def __init__(self, pool: Any, max_active: int = 8) -> None:
        self._pool = pool
        self._max_active = max_active

    async def init_schema(self) -> None:
        """No-op — schema lives in db.Database.init_schema (single source of truth)."""
        return None

    async def spawn_business(
        self,
        *,
        name: str,
        niche: str,
        genome: dict[str, Any],
        budget_gbp: float,
        parent_id: str | None = None,
        template_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str | None:
        """Atomically spawn a business if portfolio is below cap.

        Validates the genome via the Pydantic schema (raises ValueError on
        bad shape). Acquires a process-wide advisory lock before the cap
        check so concurrent spawn callers can't both exceed the cap.

        Returns business_id on success, None if at cap (caller should
        either kill a weaker business first or back off).
        """
        validated = validate_genome(genome)
        business_id = uuid.uuid4().hex
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                # Red-team #1: SELECT FOR UPDATE on COUNT doesn't lock the
                # missing rows. Advisory lock keyed on a constant serializes
                # spawn calls across the whole swarm.
                await conn.execute(
                    "SELECT pg_advisory_xact_lock($1)", _SPAWN_LOCK_KEY,
                )
                row = await conn.fetchrow(
                    "SELECT COUNT(*) AS n FROM businesses WHERE status='active'"
                )
                if int(row["n"]) >= self._max_active:
                    return None
                await conn.execute(
                    """
                    INSERT INTO businesses (
                        business_id, name, niche, genome, status,
                        parent_id, template_id, budget_remaining_gbp,
                        revenue_total_gbp, fitness_score, metadata
                    ) VALUES ($1, $2, $3, $4::jsonb, 'active',
                              $5, $6, $7, 0.0, 0.0, $8::jsonb)
                    """,
                    business_id, name, niche, json.dumps(validated),
                    parent_id, template_id, float(budget_gbp),
                    json.dumps(metadata or {}),
                )
                if template_id is not None:
                    await conn.execute(
                        "UPDATE business_templates SET times_sampled = times_sampled + 1 "
                        "WHERE template_id = $1",
                        template_id,
                    )
        return business_id

    async def kill_business(self, *, business_id: str, reason: str) -> None:
        """Mark a business killed. Releases its assets back to the pool."""
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "UPDATE businesses SET status='killed', killed_at=NOW(), "
                    "kill_reason=$2 WHERE business_id=$1 AND status='active'",
                    business_id, reason[:500],
                )
                await conn.execute(
                    "UPDATE business_assets SET owned_by_business_id=NULL, "
                    "available=TRUE, released_at=NOW() WHERE owned_by_business_id=$1",
                    business_id,
                )

    async def graduate_business(self, *, business_id: str) -> str | None:
        """Promote a business's genome to the template pool. Returns template_id.

        Idempotent: if the business already has a template in the pool,
        returns the existing template_id.
        """
        async with self._pool.acquire() as conn:
            existing = await conn.fetchrow(
                "SELECT template_id FROM business_templates WHERE source_business_id=$1",
                business_id,
            )
            if existing is not None:
                return existing["template_id"]
            biz = await conn.fetchrow(
                "SELECT name, genome, revenue_total_gbp FROM businesses WHERE business_id=$1",
                business_id,
            )
            if biz is None:
                return None
            template_id = uuid.uuid4().hex
            await conn.execute(
                "INSERT INTO business_templates (template_id, source_business_id, "
                "genome, revenue_at_graduation_gbp) VALUES ($1, $2, $3::jsonb, $4)",
                template_id, business_id,
                _to_jsonb_text(biz["genome"]),
                float(biz["revenue_total_gbp"]),
            )
            await conn.execute(
                "UPDATE businesses SET status='graduated' WHERE business_id=$1",
                business_id,
            )
        return template_id

    async def adjust_budget(self, *, business_id: str, delta_gbp: float) -> float:
        """Add (or subtract via negative delta) budget. Returns new balance."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "UPDATE businesses SET budget_remaining_gbp = "
                "GREATEST(0.0, budget_remaining_gbp + $2) "
                "WHERE business_id = $1 RETURNING budget_remaining_gbp",
                business_id, float(delta_gbp),
            )
        return float(row["budget_remaining_gbp"]) if row else 0.0

    async def update_fitness(self, *, business_id: str, fitness: float) -> None:
        fitness = max(0.0, min(1.0, float(fitness)))
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE businesses SET fitness_score=$2, last_cycle_at=NOW() "
                "WHERE business_id=$1",
                business_id, fitness,
            )

    async def record_revenue(
        self,
        *,
        business_id: str,
        amount_gbp: float,
        source: str,
        external_id: str | None = None,
        is_refund: bool = False,
        is_self_paid: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Append a revenue (or refund) event. Idempotent on (source, external_id).

        Red-team #3: `is_self_paid=True` tags revenue that came from the
        agent paying its own Stripe payment link. Fitness computation must
        exclude these to prevent Goodhart-by-self-payment.

        Red-team #4: when the business has a template_id and this is a
        non-self-paid revenue event (not refund), bumps the template's
        times_produced_revenue counter so template ranking reflects
        children's actual market success.

        Returns True if a new row was inserted, False if a duplicate was
        silently dropped. Updates revenue_total_gbp on insert.
        """
        signed = -abs(float(amount_gbp)) if is_refund else abs(float(amount_gbp))
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                inserted = await conn.fetchrow(
                    "INSERT INTO business_revenue "
                    "(business_id, amount_gbp, source, external_id, is_refund, "
                    "is_self_paid, metadata) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb) "
                    "ON CONFLICT (source, external_id) DO NOTHING "
                    "RETURNING revenue_id",
                    business_id, signed, source, external_id, is_refund,
                    is_self_paid, json.dumps(metadata or {}),
                )
                if inserted is None:
                    return False
                await conn.execute(
                    "UPDATE businesses SET revenue_total_gbp = revenue_total_gbp + $2 "
                    "WHERE business_id = $1",
                    business_id, signed,
                )
                if not is_refund and not is_self_paid:
                    await conn.execute(
                        "UPDATE business_templates SET times_produced_revenue = "
                        "times_produced_revenue + 1 "
                        "WHERE template_id = ("
                        "  SELECT template_id FROM businesses "
                        "  WHERE business_id = $1 AND template_id IS NOT NULL)",
                        business_id,
                    )
        return True

    async def get_business(self, business_id: str) -> Business | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM businesses WHERE business_id=$1", business_id,
            )
        return _row_to_business(row) if row else None

    async def list_active(self) -> list[Business]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM businesses WHERE status='active' "
                "ORDER BY fitness_score DESC, spawned_at ASC"
            )
        return [_row_to_business(r) for r in rows]

    async def count_active(self) -> int:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COUNT(*) AS n FROM businesses WHERE status='active'"
            )
        return int(row["n"])

    async def list_templates(self) -> list[BusinessTemplate]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT template_id, source_business_id, genome, "
                "revenue_at_graduation_gbp, times_sampled, times_produced_revenue "
                "FROM business_templates ORDER BY revenue_at_graduation_gbp DESC"
            )
        return [
            BusinessTemplate(
                template_id=r["template_id"],
                source_business_id=r["source_business_id"],
                genome=_jsonb_to_dict(r["genome"]),
                revenue_at_graduation_gbp=float(r["revenue_at_graduation_gbp"]),
                times_sampled=int(r["times_sampled"]),
                times_produced_revenue=int(r["times_produced_revenue"]),
            )
            for r in rows
        ]

    async def total_revenue_gbp(self) -> float:
        """Sum across all businesses, all time. The bank-account number."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COALESCE(SUM(revenue_total_gbp), 0.0) AS t FROM businesses"
            )
        return float(row["t"])


def _to_jsonb_text(value: Any) -> str:
    """asyncpg returns jsonb columns as dict OR str depending on codec. Normalise."""
    if isinstance(value, str):
        return value
    return json.dumps(value)


def _jsonb_to_dict(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        return json.loads(value)
    return {}


def _row_to_business(row: Any) -> Business:
    return Business(
        business_id=row["business_id"],
        name=row["name"],
        niche=row["niche"],
        genome=_jsonb_to_dict(row["genome"]),
        status=row["status"],
        parent_id=row["parent_id"],
        template_id=row["template_id"],
        budget_remaining_gbp=float(row["budget_remaining_gbp"]),
        revenue_total_gbp=float(row["revenue_total_gbp"]),
        fitness_score=float(row["fitness_score"]),
        spawned_at=row["spawned_at"],
        last_cycle_at=row.get("last_cycle_at") if hasattr(row, "get") else row["last_cycle_at"],
        killed_at=row["killed_at"],
        kill_reason=row["kill_reason"],
        metadata=_jsonb_to_dict(row["metadata"]),
    )
