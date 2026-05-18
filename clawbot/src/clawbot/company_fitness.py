"""Company-level fitness — one score for the organism as a whole.

The existing fitness.py scores individual agents. The meta-evaluator needs a
single number to track week-over-week. Weights are deliberate, not optimised —
revenue dominates (0.40) but plan velocity, skill-call success, and capital
efficiency each carry signal that revenue alone can't surface in week 1.

Aggregates across the FULL hypothesis portfolio — there is no per-hypothesis
fitness here. If you need that, derive it from the per-hypothesis tables
(revenue per hypothesis via causal_chain → product_causal_map → capital_ledger.metadata).

TODO(revenue-source): the revenue query depends on `action_type IN (...)`
rows being written to capital_ledger. Currently nothing in production writes
charge_authorized. Stripe webhook handler is the right next step."""
from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class CompanyFitnessScore:
    score: float
    revenue_score: float
    plan_velocity: float
    skill_call_success_rate: float
    capital_efficiency: float
    breakdown: dict


def compute_company_fitness(
    *,
    revenue_7d_gbp: Decimal,
    plans_active: int,
    plans_advanced_7d: int,
    plans_pivoted_7d: int,
    capital_deployed_7d_gbp: Decimal,
    skill_calls_7d: int,
    skill_calls_success_7d: int,
) -> CompanyFitnessScore:
    revenue_score = min(1.0, math.log1p(float(revenue_7d_gbp)) / math.log1p(100.0))

    total_plan_decisions = plans_advanced_7d + plans_pivoted_7d
    plan_velocity = (
        plans_advanced_7d / total_plan_decisions
        if total_plan_decisions > 0 else 0.0
    )

    skill_call_success_rate = (
        skill_calls_success_7d / skill_calls_7d
        if skill_calls_7d > 0 else 0.0
    )

    # Capital efficiency: revenue per £ deployed. Below £1 of deployed capital
    # the ratio is too noisy to carry signal — return 0 rather than fabricate.
    if capital_deployed_7d_gbp > Decimal("1.0"):
        capital_efficiency_raw = float(revenue_7d_gbp) / float(capital_deployed_7d_gbp)
        # Use log scaling so 1x:1 → ~0.30, 10x → ~1.0 (tier the signal)
        capital_efficiency = min(1.0, math.log1p(capital_efficiency_raw) / math.log1p(10.0))
    else:
        capital_efficiency = 0.0

    raw_score = (
        0.40 * revenue_score
        + 0.20 * plan_velocity
        + 0.20 * skill_call_success_rate
        + 0.20 * capital_efficiency
    )

    # No-activity tax: nothing happened → 0
    if skill_calls_7d == 0 and plans_advanced_7d == 0 and plans_pivoted_7d == 0:
        raw_score = 0.0

    # Goodhart guard: zero revenue caps score at 0.30
    if revenue_7d_gbp == 0:
        raw_score = min(raw_score, 0.30)

    breakdown = {
        "revenue_score": round(revenue_score, 4),
        "plan_velocity": round(plan_velocity, 4),
        "skill_call_success_rate": round(skill_call_success_rate, 4),
        "capital_efficiency": round(capital_efficiency, 4),
        "inputs": {
            "revenue_7d_gbp": float(revenue_7d_gbp),
            "plans_active": plans_active,
            "plans_advanced_7d": plans_advanced_7d,
            "plans_pivoted_7d": plans_pivoted_7d,
            "capital_deployed_7d_gbp": float(capital_deployed_7d_gbp),
            "skill_calls_7d": skill_calls_7d,
            "skill_calls_success_7d": skill_calls_success_7d,
        },
    }

    return CompanyFitnessScore(
        score=round(raw_score, 4),
        revenue_score=round(revenue_score, 4),
        plan_velocity=round(plan_velocity, 4),
        skill_call_success_rate=round(skill_call_success_rate, 4),
        capital_efficiency=round(capital_efficiency, 4),
        breakdown=breakdown,
    )


async def compute_and_snapshot(*, db_pool, today_iso: str | None = None) -> CompanyFitnessScore:
    """Query current state, compute fitness, write a snapshot row.

    Uses ON CONFLICT (snapshot_date) DO UPDATE so re-running the same day
    overwrites — supports manual debugging without piling up rows."""
    from datetime import date
    import json as _json
    snapshot_date = today_iso or date.today().isoformat()
    async with db_pool.acquire() as conn:
        # Revenue: ANY positive-amount ledger entry within window.
        # The intended action_type for revenue is 'charge_authorized', but
        # nothing in production writes that yet (TODO: Stripe webhook handler).
        # Until then, sum any positive amount: tests that record 'charge_authorized'
        # work, manual revenue entries work, and the Goodhart guard at line 70
        # behaves as designed when revenue is genuinely zero.
        rev_row = await conn.fetchrow(
            "SELECT COALESCE(SUM(amount_gbp), 0) AS rev FROM capital_ledger "
            "WHERE created_at > NOW() - INTERVAL '7 days' "
            "AND amount_gbp > 0 "
            "AND action_type IN ('charge_authorized', 'manual_revenue', 'gumroad_sale', 'paypal_sale')"
        )
        revenue_7d = Decimal(str(rev_row["rev"])) if rev_row else Decimal("0")

        plans_active_row = await conn.fetchrow(
            "SELECT COUNT(*) AS n FROM plans WHERE status='active'"
        )
        plans_active = int(plans_active_row["n"]) if plans_active_row else 0

        adv_row = await conn.fetchrow(
            "SELECT COUNT(*) AS n FROM plans WHERE status='done' "
            "AND updated_at > NOW() - INTERVAL '7 days'"
        )
        plans_advanced_7d = int(adv_row["n"]) if adv_row else 0

        piv_row = await conn.fetchrow(
            "SELECT COUNT(*) AS n FROM plans WHERE status='pivoted' "
            "AND updated_at > NOW() - INTERVAL '7 days'"
        )
        plans_pivoted_7d = int(piv_row["n"]) if piv_row else 0

        cap_row = await conn.fetchrow(
            "SELECT COALESCE(SUM(amount_gbp), 0) AS dep FROM capital_ledger "
            "WHERE action_type='card_issued' "
            "AND created_at > NOW() - INTERVAL '7 days'"
        )
        capital_deployed_7d = Decimal(str(cap_row["dep"])) if cap_row else Decimal("0")

        # skill_calls table uses `called_at` not `created_at` (see db.py:107).
        # Don't catch broad exceptions here — if the schema regresses we want
        # to know loudly, not silently report 0 to the operator.
        sc_total_row = await conn.fetchrow(
            "SELECT COUNT(*) AS n FROM skill_calls "
            "WHERE called_at > NOW() - INTERVAL '7 days'"
        )
        sc_total = int(sc_total_row["n"]) if sc_total_row else 0
        sc_ok_row = await conn.fetchrow(
            "SELECT COUNT(*) AS n FROM skill_calls "
            "WHERE called_at > NOW() - INTERVAL '7 days' AND ok = TRUE"
        )
        sc_ok = int(sc_ok_row["n"]) if sc_ok_row else 0

    score = compute_company_fitness(
        revenue_7d_gbp=revenue_7d,
        plans_active=plans_active,
        plans_advanced_7d=plans_advanced_7d,
        plans_pivoted_7d=plans_pivoted_7d,
        capital_deployed_7d_gbp=capital_deployed_7d,
        skill_calls_7d=sc_total,
        skill_calls_success_7d=sc_ok,
    )

    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO company_fitness_snapshots (
                snapshot_date, score, revenue_7d_gbp, plans_active,
                plans_advanced_7d, plans_pivoted_7d, capital_deployed_7d_gbp,
                skill_calls_7d, skill_call_success_rate, breakdown
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            ON CONFLICT (snapshot_date) DO UPDATE SET
                score = excluded.score,
                revenue_7d_gbp = excluded.revenue_7d_gbp,
                plans_active = excluded.plans_active,
                plans_advanced_7d = excluded.plans_advanced_7d,
                plans_pivoted_7d = excluded.plans_pivoted_7d,
                capital_deployed_7d_gbp = excluded.capital_deployed_7d_gbp,
                skill_calls_7d = excluded.skill_calls_7d,
                skill_call_success_rate = excluded.skill_call_success_rate,
                breakdown = excluded.breakdown
        """,
            snapshot_date, score.score, revenue_7d, plans_active,
            plans_advanced_7d, plans_pivoted_7d, capital_deployed_7d,
            sc_total, score.skill_call_success_rate,
            _json.dumps(score.breakdown),
        )

    return score
