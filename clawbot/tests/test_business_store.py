"""Swarm Phase Z1 — BusinessStore CRUD + atomicity tests.

The pure-function helper tests run unconditionally. The Postgres-backed
fixture skips when asyncpg isn't installed or no local DB is reachable."""
import pytest


def test_validate_genome_rejects_string_price():
    """Red-team #2: LLM mutations producing wrong-typed fields must error
    at spawn time, not silently corrupt the substrate."""
    from clawbot.business_store import validate_genome
    with pytest.raises(ValueError, match="invalid genome"):
        validate_genome({"niche_question": "x?", "price_gbp": "free"})


def test_validate_genome_rejects_string_channels():
    from clawbot.business_store import validate_genome
    with pytest.raises(ValueError, match="invalid genome"):
        validate_genome({
            "niche_question": "what is x?", "price_gbp": 3.0,
            "channels": "bluesky",  # must be a list
        })


def test_validate_genome_rejects_negative_price():
    from clawbot.business_store import validate_genome
    with pytest.raises(ValueError, match="invalid genome"):
        validate_genome({"niche_question": "x?", "price_gbp": -1.0})


def test_validate_genome_accepts_minimal_valid_shape():
    from clawbot.business_store import validate_genome
    out = validate_genome({"niche_question": "what band is my postcode?", "price_gbp": 3.0})
    assert out["channels"] == []
    assert out["copy_voice"] == "plain"


def test_validate_genome_normalises_channel_case():
    from clawbot.business_store import validate_genome
    out = validate_genome({
        "niche_question": "what is x?", "price_gbp": 3.0,
        "channels": ["Dev_To", "MEDIUM"],
    })
    assert out["channels"] == ["dev_to", "medium"]


def test_validate_genome_rejects_channel_with_punctuation():
    from clawbot.business_store import validate_genome
    with pytest.raises(ValueError):
        validate_genome({
            "niche_question": "x?", "price_gbp": 3.0,
            "channels": ["x.com"],  # dots disallowed
        })


def test_jsonb_to_dict_handles_dict_str_and_none():
    from clawbot.business_store import _jsonb_to_dict
    assert _jsonb_to_dict({"a": 1}) == {"a": 1}
    assert _jsonb_to_dict('{"b": 2}') == {"b": 2}
    assert _jsonb_to_dict(None) == {}


def test_to_jsonb_text_preserves_string_passthrough():
    """asyncpg returns jsonb as dict OR pre-encoded str depending on codec —
    both must round-trip safely without double-encoding."""
    from clawbot.business_store import _to_jsonb_text
    assert _to_jsonb_text({"a": 1}) == '{"a": 1}'
    assert _to_jsonb_text('{"b": 2}') == '{"b": 2}'


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


GENOME = {
    "niche_question": "what is my council tax band?",
    "price_gbp": 3.0,
    "channels": ["dev_to", "medium", "bluesky"],
    "copy_voice": "plain_uk_explainer",
    "fulfilment_template": "council_tax_v1",
}


async def _wipe(pool):
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM business_revenue WHERE source='test'")
        await conn.execute("DELETE FROM business_templates WHERE source_business_id IN "
                           "(SELECT business_id FROM businesses WHERE name LIKE 'test_z1_%')")
        await conn.execute("DELETE FROM business_assets WHERE owned_by_business_id IN "
                           "(SELECT business_id FROM businesses WHERE name LIKE 'test_z1_%')")
        await conn.execute("DELETE FROM businesses WHERE name LIKE 'test_z1_%'")


@pytest.mark.asyncio
async def test_spawn_returns_id_and_persists_row(pool):
    from clawbot.business_store import BusinessStore
    await _wipe(pool)
    store = BusinessStore(pool, max_active=8)
    bid = await store.spawn_business(
        name="test_z1_alpha", niche="council_tax", genome=GENOME,
        budget_gbp=5.0,
    )
    assert bid is not None
    biz = await store.get_business(bid)
    assert biz is not None
    assert biz.name == "test_z1_alpha"
    assert biz.status == "active"
    assert biz.genome["price_gbp"] == 3.0
    assert biz.budget_remaining_gbp == 5.0
    assert biz.revenue_total_gbp == 0.0
    await _wipe(pool)


@pytest.mark.asyncio
async def test_spawn_enforces_max_active_cap(pool):
    """Cap is the hard guard against free-tier LLM rate-limit blowups."""
    from clawbot.business_store import BusinessStore
    await _wipe(pool)
    store = BusinessStore(pool, max_active=2)
    a = await store.spawn_business(name="test_z1_a", niche="x", genome=GENOME, budget_gbp=1.0)
    b = await store.spawn_business(name="test_z1_b", niche="x", genome=GENOME, budget_gbp=1.0)
    c = await store.spawn_business(name="test_z1_c", niche="x", genome=GENOME, budget_gbp=1.0)
    assert a is not None and b is not None
    assert c is None, "third spawn must be refused when cap=2 and both prior are active"
    await _wipe(pool)


@pytest.mark.asyncio
async def test_killing_a_business_frees_a_slot(pool):
    from clawbot.business_store import BusinessStore
    await _wipe(pool)
    store = BusinessStore(pool, max_active=2)
    a = await store.spawn_business(name="test_z1_a", niche="x", genome=GENOME, budget_gbp=1.0)
    b = await store.spawn_business(name="test_z1_b", niche="x", genome=GENOME, budget_gbp=1.0)
    assert a and b
    await store.kill_business(business_id=a, reason="test")
    c = await store.spawn_business(name="test_z1_c", niche="x", genome=GENOME, budget_gbp=1.0)
    assert c is not None, "slot must reopen after kill"
    biz_a = await store.get_business(a)
    assert biz_a and biz_a.status == "killed" and biz_a.kill_reason == "test"
    await _wipe(pool)


@pytest.mark.asyncio
async def test_record_revenue_is_idempotent_per_external_id(pool):
    """Stripe webhook retries must not double-count a charge."""
    from clawbot.business_store import BusinessStore
    await _wipe(pool)
    store = BusinessStore(pool, max_active=4)
    bid = await store.spawn_business(name="test_z1_rev", niche="x", genome=GENOME, budget_gbp=1.0)
    assert bid
    first = await store.record_revenue(
        business_id=bid, amount_gbp=3.0, source="test", external_id="ch_abc",
    )
    second = await store.record_revenue(
        business_id=bid, amount_gbp=3.0, source="test", external_id="ch_abc",
    )
    assert first is True
    assert second is False, "duplicate (source, external_id) must be dropped"
    biz = await store.get_business(bid)
    assert biz and biz.revenue_total_gbp == 3.0, "total must reflect one charge, not two"
    await _wipe(pool)


@pytest.mark.asyncio
async def test_refund_subtracts_from_revenue_total(pool):
    from clawbot.business_store import BusinessStore
    await _wipe(pool)
    store = BusinessStore(pool, max_active=4)
    bid = await store.spawn_business(name="test_z1_ref", niche="x", genome=GENOME, budget_gbp=1.0)
    assert bid
    await store.record_revenue(business_id=bid, amount_gbp=5.0, source="test", external_id="ch_1")
    await store.record_revenue(
        business_id=bid, amount_gbp=2.0, source="test", external_id="re_1", is_refund=True,
    )
    biz = await store.get_business(bid)
    assert biz and biz.revenue_total_gbp == 3.0
    await _wipe(pool)


@pytest.mark.asyncio
async def test_adjust_budget_clamps_at_zero(pool):
    """Budget cannot go negative — death happens via kill, not via overdraft."""
    from clawbot.business_store import BusinessStore
    await _wipe(pool)
    store = BusinessStore(pool, max_active=4)
    bid = await store.spawn_business(name="test_z1_b", niche="x", genome=GENOME, budget_gbp=2.0)
    assert bid
    new_balance = await store.adjust_budget(business_id=bid, delta_gbp=-5.0)
    assert new_balance == 0.0
    await _wipe(pool)


@pytest.mark.asyncio
async def test_graduate_creates_template_and_is_idempotent(pool):
    from clawbot.business_store import BusinessStore
    await _wipe(pool)
    store = BusinessStore(pool, max_active=4)
    bid = await store.spawn_business(name="test_z1_grad", niche="x", genome=GENOME, budget_gbp=1.0)
    assert bid
    await store.record_revenue(business_id=bid, amount_gbp=75.0, source="test", external_id="ch_grad")
    tid1 = await store.graduate_business(business_id=bid)
    tid2 = await store.graduate_business(business_id=bid)
    assert tid1 is not None
    assert tid1 == tid2, "second graduate call must return the existing template_id"
    templates = await store.list_templates()
    assert any(t.template_id == tid1 for t in templates)
    biz = await store.get_business(bid)
    assert biz and biz.status == "graduated"
    await _wipe(pool)


@pytest.mark.asyncio
async def test_spawn_from_template_increments_sampled_counter(pool):
    from clawbot.business_store import BusinessStore
    await _wipe(pool)
    store = BusinessStore(pool, max_active=4)
    src = await store.spawn_business(name="test_z1_src", niche="x", genome=GENOME, budget_gbp=1.0)
    assert src
    await store.record_revenue(business_id=src, amount_gbp=60.0, source="test", external_id="ch_s")
    tid = await store.graduate_business(business_id=src)
    assert tid
    child = await store.spawn_business(
        name="test_z1_child", niche="x", genome=GENOME, budget_gbp=1.0,
        parent_id=src, template_id=tid,
    )
    assert child
    templates = await store.list_templates()
    t = next(t for t in templates if t.template_id == tid)
    assert t.times_sampled == 1
    await _wipe(pool)


@pytest.mark.asyncio
async def test_self_paid_revenue_does_not_inflate_business_revenue_total(pool):
    """Z2 red-team: self-paid revenue tagging on the events table isn't
    enough — the rolled-up `businesses.revenue_total_gbp` is what fitness
    reads, so it must also exclude self-paid."""
    from clawbot.business_store import BusinessStore
    await _wipe(pool)
    store = BusinessStore(pool, max_active=4)
    bid = await store.spawn_business(
        name="test_z1_sp", niche="x", genome=GENOME, budget_gbp=1.0,
    )
    assert bid
    await store.record_revenue(
        business_id=bid, amount_gbp=20.0, source="test", external_id="sp_1",
        is_self_paid=True,
    )
    biz = await store.get_business(bid)
    assert biz and biz.revenue_total_gbp == 0.0, (
        "self-paid revenue must NOT inflate revenue_total_gbp — fitness reads this column"
    )
    # Real revenue still counts
    await store.record_revenue(
        business_id=bid, amount_gbp=7.0, source="test", external_id="real_1",
    )
    biz = await store.get_business(bid)
    assert biz and biz.revenue_total_gbp == 7.0
    await _wipe(pool)


@pytest.mark.asyncio
async def test_self_paid_revenue_is_flagged_and_does_not_bump_template_counter(pool):
    """Red-team #3+#4: self-paid revenue tracked separately from real customer
    revenue; template counter only bumps for genuine market revenue."""
    from clawbot.business_store import BusinessStore
    await _wipe(pool)
    store = BusinessStore(pool, max_active=4)
    parent = await store.spawn_business(
        name="test_z1_parent", niche="x", genome=GENOME, budget_gbp=1.0,
    )
    assert parent
    await store.record_revenue(
        business_id=parent, amount_gbp=60.0, source="test", external_id="ch_p",
    )
    tid = await store.graduate_business(business_id=parent)
    assert tid
    child = await store.spawn_business(
        name="test_z1_child", niche="x", genome=GENOME, budget_gbp=1.0,
        parent_id=parent, template_id=tid,
    )
    assert child

    # Self-paid revenue: must NOT bump template counter, must be queryable
    await store.record_revenue(
        business_id=child, amount_gbp=10.0, source="test", external_id="self_1",
        is_self_paid=True,
    )
    templates = await store.list_templates()
    t = next(t for t in templates if t.template_id == tid)
    assert t.times_produced_revenue == 0, "self-paid revenue must not credit the template"

    # Real revenue: MUST bump template counter
    await store.record_revenue(
        business_id=child, amount_gbp=5.0, source="test", external_id="real_1",
    )
    templates = await store.list_templates()
    t = next(t for t in templates if t.template_id == tid)
    assert t.times_produced_revenue == 1

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT is_self_paid FROM business_revenue WHERE external_id='self_1'"
        )
    assert row and row["is_self_paid"] is True
    await _wipe(pool)


@pytest.mark.asyncio
async def test_spawn_rejects_invalid_genome(pool):
    """Genome validation must fire at spawn — before any row is inserted."""
    from clawbot.business_store import BusinessStore
    await _wipe(pool)
    store = BusinessStore(pool, max_active=4)
    with pytest.raises(ValueError, match="invalid genome"):
        await store.spawn_business(
            name="test_z1_bad", niche="x",
            genome={"niche_question": "x?", "price_gbp": "free"},
            budget_gbp=1.0,
        )
    count = await store.count_active()
    # Should not have inserted anything
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT COUNT(*) AS n FROM businesses WHERE name='test_z1_bad'"
        )
    assert int(row["n"]) == 0
    await _wipe(pool)
    _ = count  # silence unused


@pytest.mark.asyncio
async def test_total_revenue_sums_across_businesses(pool):
    from clawbot.business_store import BusinessStore
    await _wipe(pool)
    store = BusinessStore(pool, max_active=4)
    a = await store.spawn_business(name="test_z1_ta", niche="x", genome=GENOME, budget_gbp=1.0)
    b = await store.spawn_business(name="test_z1_tb", niche="x", genome=GENOME, budget_gbp=1.0)
    assert a and b
    await store.record_revenue(business_id=a, amount_gbp=7.0, source="test", external_id="x1")
    await store.record_revenue(business_id=b, amount_gbp=11.0, source="test", external_id="x2")
    before = await store.total_revenue_gbp()
    assert before >= 18.0
    await _wipe(pool)
