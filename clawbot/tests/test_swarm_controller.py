"""Swarm Phase Z2 — SwarmController fitness math, sampling, and lifecycle tests.

The pure-function tests (compute_business_fitness, should_kill, sample_genome)
run unconditionally. The Postgres-backed bootstrap/spawn/cull tests skip
locally when asyncpg/Postgres aren't available."""
import random
from datetime import datetime, timedelta, timezone

import pytest

UTC = timezone.utc


def _make_business(*, business_id="bid1", name="t", niche="x", revenue=0.0,
                   spawned_days_ago=0.0, fitness=0.0):
    """Build a minimal frozen Business stand-in for fitness/kill tests."""
    from clawbot.business_store import Business
    return Business(
        business_id=business_id, name=name, niche=niche,
        genome={"niche_question": "x?", "price_gbp": 3.0},
        status="active", parent_id=None, template_id=None,
        budget_remaining_gbp=1.0, revenue_total_gbp=float(revenue),
        fitness_score=float(fitness),
        spawned_at=datetime.now(UTC) - timedelta(days=spawned_days_ago),
        last_cycle_at=None, killed_at=None, kill_reason=None, metadata={},
    )


# ---- fitness math ----

def test_fitness_neutral_for_newborn():
    from clawbot.swarm_controller import compute_business_fitness
    b = _make_business(spawned_days_ago=0.2, revenue=0.0)
    assert compute_business_fitness(b) == 0.5


def test_fitness_zero_for_aged_zero_revenue():
    """Day-7 with £0 should be deep in the unfit zone — kill candidate."""
    from clawbot.swarm_controller import compute_business_fitness
    b = _make_business(spawned_days_ago=7.0, revenue=0.0)
    assert compute_business_fitness(b) == 0.0


def test_fitness_climbs_with_revenue():
    """A business meeting expectations gets ~0.5, doubling gets ~0.67."""
    from clawbot.swarm_controller import compute_business_fitness
    on_target = _make_business(spawned_days_ago=14.0, revenue=5.0)
    above = _make_business(spawned_days_ago=14.0, revenue=20.0)
    f_on = compute_business_fitness(on_target)
    f_above = compute_business_fitness(above)
    assert 0.4 < f_on < 0.6, f"on-target should be ~0.5; got {f_on}"
    assert f_above > f_on, f"above-target ({f_above}) must beat on-target ({f_on})"
    assert f_above <= 1.0


# ---- kill rules ----

def test_should_kill_after_probation_zero_revenue():
    from clawbot.swarm_controller import SwarmPolicy, should_kill
    policy = SwarmPolicy(
        max_active=8, seed_budget_gbp=1.0, graduation_revenue_gbp=50.0,
        probation_days=14.0, hard_kill_days=21.0, template_sample_weight=0.7,
    )
    b = _make_business(spawned_days_ago=15.0, revenue=0.0)
    kill, reason = should_kill(b, policy=policy)
    assert kill is True
    assert "failed_probation" in reason


def test_should_not_kill_within_probation_even_at_zero_revenue():
    from clawbot.swarm_controller import SwarmPolicy, should_kill
    policy = SwarmPolicy(
        max_active=8, seed_budget_gbp=1.0, graduation_revenue_gbp=50.0,
        probation_days=14.0, hard_kill_days=21.0, template_sample_weight=0.7,
    )
    b = _make_business(spawned_days_ago=7.0, revenue=0.0)
    kill, _ = should_kill(b, policy=policy)
    assert kill is False


def test_should_kill_at_hard_threshold_with_below_5_revenue():
    """Past hard_kill, sub-£5 net = death. Even if probation already passed,
    this is the second-tier rule for sluggish but not-zero businesses."""
    from clawbot.swarm_controller import SwarmPolicy, should_kill
    policy = SwarmPolicy(
        max_active=8, seed_budget_gbp=1.0, graduation_revenue_gbp=50.0,
        probation_days=14.0, hard_kill_days=21.0, template_sample_weight=0.7,
    )
    b = _make_business(spawned_days_ago=22.0, revenue=3.0)
    kill, reason = should_kill(b, policy=policy)
    assert kill is True
    assert "below_threshold" in reason


def test_should_not_kill_at_hard_threshold_above_5_revenue():
    from clawbot.swarm_controller import SwarmPolicy, should_kill
    policy = SwarmPolicy(
        max_active=8, seed_budget_gbp=1.0, graduation_revenue_gbp=50.0,
        probation_days=14.0, hard_kill_days=21.0, template_sample_weight=0.7,
    )
    b = _make_business(spawned_days_ago=22.0, revenue=8.0)
    kill, _ = should_kill(b, policy=policy)
    assert kill is False


# ---- sampling ----

def test_sample_genome_falls_back_to_seeds_when_templates_empty():
    from clawbot.swarm_controller import SwarmPolicy, sample_genome
    from clawbot.swarm_seeds import get_seed_genomes
    policy = SwarmPolicy(
        max_active=8, seed_budget_gbp=1.0, graduation_revenue_gbp=50.0,
        probation_days=14.0, hard_kill_days=21.0, template_sample_weight=1.0,
    )
    g = sample_genome(
        templates=[], seeds=get_seed_genomes(),
        policy=policy, rng=random.Random(42),
    )
    assert "niche_question" in g
    assert g["price_gbp"] > 0


def test_sample_genome_raises_when_no_genomes_available():
    from clawbot.swarm_controller import SwarmPolicy, sample_genome
    policy = SwarmPolicy(
        max_active=8, seed_budget_gbp=1.0, graduation_revenue_gbp=50.0,
        probation_days=14.0, hard_kill_days=21.0, template_sample_weight=0.7,
    )
    with pytest.raises(ValueError, match="no genomes"):
        sample_genome(templates=[], seeds=[], policy=policy)


def test_sample_genome_template_weighting_favors_productive_template():
    """A template with high produced/sampled ratio must dominate sampling."""
    from clawbot.swarm_controller import SwarmPolicy, sample_genome
    from clawbot.business_store import BusinessTemplate
    from clawbot.swarm_seeds import get_seed_genomes
    valid_genome = get_seed_genomes()[0]
    other_genome = get_seed_genomes()[1]
    productive = BusinessTemplate(
        template_id="tp_good", source_business_id="b1",
        genome=valid_genome,
        revenue_at_graduation_gbp=100.0, times_sampled=10, times_produced_revenue=10,
    )
    dud = BusinessTemplate(
        template_id="tp_dud", source_business_id="b2",
        genome=other_genome,
        revenue_at_graduation_gbp=51.0, times_sampled=10, times_produced_revenue=0,
    )
    policy = SwarmPolicy(
        max_active=8, seed_budget_gbp=1.0, graduation_revenue_gbp=50.0,
        probation_days=14.0, hard_kill_days=21.0, template_sample_weight=1.0,
    )
    rng = random.Random(7)
    productive_picks = 0
    for _ in range(200):
        g = sample_genome(templates=[productive, dud], seeds=[], policy=policy, rng=rng)
        if g["fulfilment_template"] == valid_genome["fulfilment_template"]:
            productive_picks += 1
    # weighting: productive (1+10)/(1+10)=1.0, dud (1+0)/(1+10)=0.09
    # → productive should win ~91% of the time. Loose bound for noise.
    assert productive_picks > 150, f"productive template only won {productive_picks}/200 — weighting broken"


# ---- seed pool validity ----

def test_all_seeds_are_valid_genomes():
    """Every seed genome must pass Pydantic validation — otherwise bootstrap dies."""
    from clawbot.business_store import validate_genome
    from clawbot.swarm_seeds import get_seed_genomes
    for seed in get_seed_genomes():
        validated = validate_genome(seed)
        assert validated["price_gbp"] > 0
        assert isinstance(validated["channels"], list) and validated["channels"]


def test_get_seed_genomes_returns_copies_not_aliases():
    """Mutating a returned seed must not affect the module-level pool."""
    from clawbot.swarm_seeds import get_seed_genomes, SEED_GENOMES
    seeds = get_seed_genomes()
    seeds[0]["price_gbp"] = 9999.0
    assert SEED_GENOMES[0]["price_gbp"] != 9999.0


# ---- Postgres-backed integration ----

@pytest.fixture
async def pool():
    asyncpg = pytest.importorskip("asyncpg")
    try:
        pool = await asyncpg.create_pool(
            "postgresql://clawbot:clawbot@localhost:5432/clawbot",
            min_size=1, max_size=4,
        )
    except Exception:
        pytest.skip("local Postgres not available")
    yield pool
    await pool.close()


async def _wipe(pool):
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM business_revenue WHERE source='test_z2'")
        await conn.execute("DELETE FROM business_templates WHERE source_business_id IN "
                           "(SELECT business_id FROM businesses WHERE name LIKE 'seed_%' "
                           "OR name LIKE 'spawn_%' OR name LIKE 'test_z2_%')")
        await conn.execute("DELETE FROM business_assets WHERE owned_by_business_id IN "
                           "(SELECT business_id FROM businesses WHERE name LIKE 'seed_%' "
                           "OR name LIKE 'spawn_%' OR name LIKE 'test_z2_%')")
        await conn.execute("DELETE FROM businesses WHERE name LIKE 'seed_%' "
                           "OR name LIKE 'spawn_%' OR name LIKE 'test_z2_%'")


def _policy(**overrides):
    from clawbot.swarm_controller import SwarmPolicy
    base = {
        "max_active": 8, "seed_budget_gbp": 1.0, "graduation_revenue_gbp": 50.0,
        "probation_days": 14.0, "hard_kill_days": 21.0, "template_sample_weight": 0.7,
    }
    base.update(overrides)
    return SwarmPolicy(**base)


@pytest.mark.asyncio
async def test_bootstrap_seeds_when_empty(pool):
    from clawbot.business_store import BusinessStore
    from clawbot.swarm_controller import SwarmController
    from clawbot.swarm_seeds import get_seed_genomes
    await _wipe(pool)
    store = BusinessStore(pool, max_active=8)
    ctl = SwarmController(store=store, seeds=get_seed_genomes(), policy=_policy())
    n = await ctl.bootstrap_if_empty()
    assert n == len(get_seed_genomes())
    n2 = await ctl.bootstrap_if_empty()
    assert n2 == 0, "second bootstrap must be a no-op"
    await _wipe(pool)


@pytest.mark.asyncio
async def test_spawn_one_respects_cap(pool):
    from clawbot.business_store import BusinessStore
    from clawbot.swarm_controller import SwarmController
    from clawbot.swarm_seeds import get_seed_genomes
    await _wipe(pool)
    store = BusinessStore(pool, max_active=2)
    ctl = SwarmController(
        store=store, seeds=get_seed_genomes(), policy=_policy(max_active=2),
        rng=random.Random(1),
    )
    a = await ctl.spawn_one()
    b = await ctl.spawn_one()
    c = await ctl.spawn_one()
    assert a is not None and b is not None
    assert c is None, "third spawn must be refused at cap=2"
    await _wipe(pool)


@pytest.mark.asyncio
async def test_cull_kills_aged_zero_revenue_business(pool):
    from clawbot.business_store import BusinessStore
    from clawbot.swarm_controller import SwarmController
    from clawbot.swarm_seeds import get_seed_genomes
    await _wipe(pool)
    store = BusinessStore(pool, max_active=4)
    ctl = SwarmController(
        store=store, seeds=get_seed_genomes(), policy=_policy(probation_days=1.0),
    )
    bid = await store.spawn_business(
        name="test_z2_cull", niche="x", genome=get_seed_genomes()[0], budget_gbp=1.0,
    )
    assert bid
    # Backdate spawned_at to 2 days ago so it's past probation_days=1.0
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE businesses SET spawned_at = NOW() - INTERVAL '2 days' "
            "WHERE business_id=$1", bid,
        )
    killed = await ctl.cull_one_pass()
    assert killed == 1
    biz = await store.get_business(bid)
    assert biz and biz.status == "killed"
    await _wipe(pool)


@pytest.mark.asyncio
async def test_graduate_eligible_promotes_high_revenue_business(pool):
    from clawbot.business_store import BusinessStore
    from clawbot.swarm_controller import SwarmController
    from clawbot.swarm_seeds import get_seed_genomes
    await _wipe(pool)
    store = BusinessStore(pool, max_active=4)
    ctl = SwarmController(
        store=store, seeds=get_seed_genomes(), policy=_policy(graduation_revenue_gbp=10.0),
    )
    bid = await store.spawn_business(
        name="test_z2_grad", niche="x", genome=get_seed_genomes()[0], budget_gbp=1.0,
    )
    assert bid
    await store.record_revenue(
        business_id=bid, amount_gbp=15.0, source="test_z2", external_id="ch_grad",
    )
    n = await ctl.graduate_eligible()
    assert n == 1
    biz = await store.get_business(bid)
    assert biz and biz.status == "graduated"
    await _wipe(pool)


@pytest.mark.asyncio
async def test_status_reports_swarm_shape(pool):
    from clawbot.business_store import BusinessStore
    from clawbot.swarm_controller import SwarmController
    from clawbot.swarm_seeds import get_seed_genomes
    await _wipe(pool)
    store = BusinessStore(pool, max_active=4)
    ctl = SwarmController(store=store, seeds=get_seed_genomes(), policy=_policy())
    await ctl.bootstrap_if_empty()
    snap = await ctl.status()
    assert snap["active_count"] == len(get_seed_genomes())
    assert snap["active_cap"] == 8
    assert "active" in snap
    assert len(snap["active"]) == len(get_seed_genomes())
    await _wipe(pool)
