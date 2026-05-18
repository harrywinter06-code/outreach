"""
Swarm Phase Z2 — continuous monitor that spawns, evaluates, and culls
businesses against the measured £-fitness signal.

Three loops, all idempotent, all firing on their own intervals:

1. **spawn loop** — if `count_active < cap`, sample a genome from
   templates (Thompson-weighted by produced-revenue rate) or from the
   seed pool (cold start), then spawn one business.

2. **cull loop** — for each active business: compute fitness from net
   revenue and age, update fitness_score, kill if past probation with
   zero revenue OR past hard-kill threshold with sub-target revenue.

3. **graduation loop** — promote any business above the graduation
   revenue threshold to the template pool, where it seeds future spawns.

Design notes:
- No LLM calls — selection pressure is deterministic policy over
  measured signals. The "intelligence" comes from the population
  dynamics, not from a meta-agent reasoning about each business.
- All three loops are safe to run concurrently with each other and with
  themselves (BusinessStore primitives are atomic / idempotent).
- Free-tier-LLM constraint shaped the cadence: 6h intervals avoid
  burning the executive cycle budget on swarm maintenance.

Phase Z3 will add per-business activity-score (skill_call success rate),
asset-pool acquisition, capital recycling. Phase Z4 will add genome
mutation operators + crossover for richer template sampling.
"""
from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from clawbot.business_store import Business, BusinessStore, validate_genome

logger = logging.getLogger(__name__)

UTC = timezone.utc


@dataclass(frozen=True)
class SwarmPolicy:
    """All knobs the SwarmController respects. Lifted from Settings at
    construction so loops don't re-read config every tick."""
    max_active: int
    seed_budget_gbp: float
    graduation_revenue_gbp: float
    probation_days: float
    hard_kill_days: float
    template_sample_weight: float  # 0.0-1.0 — share of spawns drawn from templates


def compute_business_fitness(
    biz: Business, *, now: datetime | None = None, activity_score: int = 0,
) -> float:
    """Map (age, net_revenue, activity) → fitness in [0.0, 1.0].

    Revenue ratio: `sigmoid(ratio - 1)`-ish, where ratio = net_revenue / expected.
    Expected ramp: £0 day 0 → £1 day 7 → £5 day 14 → £20 day 30 → +£0.5/day.

    Activity penalty (Z2.5b): a business older than 1 day with ZERO successful
    skill_calls in 72h is sleepwalking. Halve its fitness so it sorts under
    actively-trying peers. Even a revenue-positive but inactive business is
    a cull candidate — revenue without ongoing work suggests luck, not skill.

    A brand-new business (age < 1d) gets 0.5 (neutral). Refunds and
    self-paid revenue are already netted in `revenue_total_gbp` by
    `BusinessStore.record_revenue`.
    """
    now = now or datetime.now(UTC)
    spawned = biz.spawned_at
    if spawned.tzinfo is None:
        spawned = spawned.replace(tzinfo=UTC)
    age_days = (now - spawned).total_seconds() / 86_400.0
    if age_days < 1.0:
        return 0.5
    net = max(0.0, biz.revenue_total_gbp)
    if age_days <= 7.0:
        expected = max(0.01, age_days / 7.0)
    elif age_days <= 14.0:
        expected = 1.0 + (age_days - 7.0) * (4.0 / 7.0)
    elif age_days <= 30.0:
        expected = 5.0 + (age_days - 14.0) * (15.0 / 16.0)
    else:
        expected = 20.0 + (age_days - 30.0) * 0.5
    ratio = net / expected
    fitness = min(1.0, max(0.0, ratio / (1.0 + ratio)))
    if activity_score == 0:
        fitness *= 0.5
    return fitness


def should_kill(
    biz: Business, *, policy: SwarmPolicy, now: datetime | None = None,
    stall_threshold: int = 3,
) -> tuple[bool, str]:
    """Deterministic kill rule. Returns (kill?, reason).

    Three rules, evaluated in order:
    1. Stalled: artifact_stall_count >= threshold AND age >= 7d AND net = 0
       → narrators die. Z2.5b addition.
    2. Failed probation: past probation_days with zero net revenue.
    3. Below threshold: past hard_kill_days with sub-£5 net revenue.
    """
    now = now or datetime.now(UTC)
    spawned = biz.spawned_at
    if spawned.tzinfo is None:
        spawned = spawned.replace(tzinfo=UTC)
    age_days = (now - spawned).total_seconds() / 86_400.0
    net = max(0.0, biz.revenue_total_gbp)
    stall = int((biz.metadata or {}).get("artifact_stall_count", 0))
    if stall >= stall_threshold and age_days >= 7.0 and net == 0.0:
        return True, f"stalled_no_artifacts:stall={stall},age={age_days:.1f}d"
    if age_days >= policy.probation_days and net == 0.0:
        return True, f"failed_probation:age={age_days:.1f}d,net=£0"
    if age_days >= policy.hard_kill_days and net < 5.0:
        return True, f"below_threshold:age={age_days:.1f}d,net=£{net:.2f}"
    return False, ""


def sample_genome(
    *,
    templates: list[Any],
    seeds: list[dict],
    policy: SwarmPolicy,
    rng: random.Random | None = None,
) -> dict:
    """Pick one genome for the next spawn.

    Policy: with probability `template_sample_weight`, draw from templates
    weighted by `(1 + times_produced_revenue) / (1 + times_sampled)`
    (Laplace-smoothed produced-revenue rate). Otherwise draw uniformly
    from the seed pool. If templates is empty, always draw from seeds.

    Returns a validated genome dict (raises ValueError if neither pool
    yields a valid genome, which means the swarm is misconfigured).
    """
    rng = rng or random.Random()
    use_template = templates and rng.random() < policy.template_sample_weight
    if use_template:
        weights = [
            (1.0 + t.times_produced_revenue) / (1.0 + t.times_sampled)
            for t in templates
        ]
        choice = rng.choices(templates, weights=weights, k=1)[0]
        return validate_genome(dict(choice.genome))
    if not seeds:
        raise ValueError("swarm has no genomes to sample (templates and seeds both empty)")
    return validate_genome(dict(rng.choice(seeds)))


class SwarmController:
    """Continuous spawn / cull / graduate loops over the business population."""

    def __init__(
        self,
        store: BusinessStore,
        *,
        seeds: list[dict],
        policy: SwarmPolicy,
        rng: random.Random | None = None,
    ) -> None:
        self._store = store
        self._seeds = seeds
        self._policy = policy
        self._rng = rng or random.Random()
        # cumulative counters for telemetry — read by swarm_status skill
        self.spawn_count = 0
        self.cull_count = 0
        self.graduation_count = 0

    @property
    def policy(self) -> SwarmPolicy:
        return self._policy

    async def bootstrap_if_empty(self) -> int:
        """If 0 active businesses AND 0 templates, seed N businesses from
        the seed pool. Idempotent: re-running with an existing population
        is a no-op. Returns number bootstrapped."""
        active = await self._store.count_active()
        templates = await self._store.list_templates()
        if active > 0 or templates:
            return 0
        # Bootstrap: spawn one business per seed genome (up to cap),
        # so the swarm has population diversity from cycle 1.
        seeded = 0
        for seed in self._seeds[: self._policy.max_active]:
            bid = await self._store.spawn_business(
                name=f"seed_{seed['fulfilment_template']}_{seeded}",
                niche=seed.get("niche_question", "unknown")[:80],
                genome=seed,
                budget_gbp=self._policy.seed_budget_gbp,
                metadata={"source": "bootstrap_seed"},
            )
            if bid is not None:
                seeded += 1
                self.spawn_count += 1
                logger.info("Bootstrap spawned business %s from seed %s", bid, seed["fulfilment_template"])
        return seeded

    async def spawn_one(self) -> str | None:
        """If under cap, sample a genome and spawn one. Returns business_id."""
        active = await self._store.count_active()
        if active >= self._policy.max_active:
            return None
        templates = await self._store.list_templates()
        genome = sample_genome(
            templates=templates, seeds=self._seeds,
            policy=self._policy, rng=self._rng,
        )
        # Name = template_id|seed key + random suffix for traceability
        template_choice_id = None
        if templates and genome in [t.genome for t in templates]:
            template_choice_id = next(
                (t.template_id for t in templates if t.genome == genome), None
            )
        suffix = self._rng.randint(1000, 9999)
        name = (
            f"spawn_{genome.get('fulfilment_template', 'tpl')}_{suffix}"
            if template_choice_id is None
            else f"spawn_tpl_{template_choice_id[:8]}_{suffix}"
        )
        bid = await self._store.spawn_business(
            name=name[:120],
            niche=genome.get("niche_question", "unknown")[:80],
            genome=genome,
            budget_gbp=self._policy.seed_budget_gbp,
            template_id=template_choice_id,
            metadata={"source": "spawn_loop"},
        )
        if bid is not None:
            self.spawn_count += 1
            logger.info(
                "Spawned business %s (template=%s, niche=%s)",
                bid, template_choice_id, genome.get("niche_question", "?")[:60],
            )
        return bid

    async def cull_one_pass(self) -> int:
        """Recompute fitness for each active business; kill the unfit.
        Returns number killed in this pass.

        Reads per-business activity score from skill_calls (Z2.5b) to apply
        the inactivity penalty before deciding kill — a business that
        produces revenue but stops trying is still a cull candidate."""
        active = await self._store.list_active()
        now = datetime.now(UTC)
        killed = 0
        for biz in active:
            try:
                activity = await self._store.activity_score_72h(biz.business_id)
            except Exception as exc:
                logger.warning("activity_score read failed for %s: %s", biz.business_id, exc)
                activity = 0
            fitness = compute_business_fitness(biz, now=now, activity_score=activity)
            await self._store.update_fitness(business_id=biz.business_id, fitness=fitness)
            kill, reason = should_kill(biz, policy=self._policy, now=now)
            if kill:
                await self._store.kill_business(business_id=biz.business_id, reason=reason)
                killed += 1
                self.cull_count += 1
                logger.info(
                    "Culled business %s (name=%s, reason=%s)",
                    biz.business_id, biz.name, reason,
                )
        return killed

    async def graduate_eligible(self) -> int:
        """Promote any business with revenue >= graduation_revenue_gbp to
        the template pool. Returns number graduated."""
        active = await self._store.list_active()
        graduated = 0
        for biz in active:
            if biz.revenue_total_gbp >= self._policy.graduation_revenue_gbp:
                tid = await self._store.graduate_business(business_id=biz.business_id)
                if tid is not None:
                    graduated += 1
                    self.graduation_count += 1
                    logger.info(
                        "Graduated business %s to template %s (revenue=£%.2f)",
                        biz.business_id, tid, biz.revenue_total_gbp,
                    )
        return graduated

    async def status(self) -> dict:
        """Snapshot of swarm state for the operator dashboard / swarm_status skill."""
        active_list = await self._store.list_active()
        templates = await self._store.list_templates()
        total_rev = await self._store.total_revenue_gbp()
        return {
            "active_count": len(active_list),
            "active_cap": self._policy.max_active,
            "template_count": len(templates),
            "total_revenue_gbp": round(total_rev, 2),
            "cumulative_spawned": self.spawn_count,
            "cumulative_culled": self.cull_count,
            "cumulative_graduated": self.graduation_count,
            "active": [
                {
                    "business_id": b.business_id[:12],
                    "name": b.name,
                    "niche": b.niche[:60],
                    "fitness": float(b.fitness_score),
                    "revenue_gbp": float(b.revenue_total_gbp),
                    "budget_gbp": float(b.budget_remaining_gbp),
                    "spawned_at": b.spawned_at.isoformat(),
                }
                for b in active_list
            ],
        }

    async def run_spawn_loop(self, interval_s: float) -> None:
        """Long-running: bootstrap on first tick, then spawn one per interval
        when capacity exists. Respects `settings.swarm_freeze` for emergency
        stop without container restart. Cancellation-safe."""
        from clawbot.config import settings
        try:
            await self.bootstrap_if_empty()
        except Exception as exc:
            logger.error("Swarm bootstrap failed: %s", exc, exc_info=True)
        while True:
            await asyncio.sleep(interval_s)
            if settings.swarm_freeze:
                logger.info("Swarm spawn loop paused (swarm_freeze=true)")
                continue
            try:
                await self.spawn_one()
            except Exception as exc:
                logger.error("Swarm spawn tick failed: %s", exc, exc_info=True)

    async def run_cull_loop(self, interval_s: float) -> None:
        """Long-running: every interval, recompute fitness + cull unfit +
        graduate winners. One coroutine handles all three so they share
        a single DB read of the active list."""
        while True:
            await asyncio.sleep(interval_s)
            try:
                await self.cull_one_pass()
                await self.graduate_eligible()
            except Exception as exc:
                logger.error("Swarm cull tick failed: %s", exc, exc_info=True)
