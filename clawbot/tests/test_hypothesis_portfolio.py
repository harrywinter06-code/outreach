"""Multi-hypothesis portfolio — 1 to N active simultaneously."""
import json
import pytest
asyncpg = pytest.importorskip("asyncpg")


@pytest.fixture
async def pool():
    try:
        pool = await asyncpg.create_pool(
            "postgresql://clawbot:clawbot@localhost:5432/clawbot",
            min_size=1, max_size=2,
        )
    except Exception:
        pytest.skip("local Postgres not available")
    yield pool
    await pool.close()


@pytest.mark.asyncio
async def test_add_hypothesis_does_not_supersede_previous(pool):
    """Old `set_active` superseded the previous row. `add_hypothesis` does NOT."""
    from clawbot.hypothesis_store import HypothesisStore
    store = HypothesisStore(pool)
    await store.init_schema()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM active_hypothesis WHERE name LIKE 'test_pf_%'")

    id_a = await store.add_hypothesis(name="test_pf_A", description="bet A",
                                       kill_criteria={"max_days_without_revenue": 14},
                                       weight=0.5)
    id_b = await store.add_hypothesis(name="test_pf_B", description="bet B",
                                       kill_criteria={"max_days_without_revenue": 14},
                                       weight=0.5)
    portfolio = await store.get_active_portfolio()
    names = {h["name"] for h in portfolio if h["name"].startswith("test_pf_")}
    assert names == {"test_pf_A", "test_pf_B"}


@pytest.mark.asyncio
async def test_kill_hypothesis_by_id_only_kills_that_one(pool):
    from clawbot.hypothesis_store import HypothesisStore
    store = HypothesisStore(pool)
    await store.init_schema()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM active_hypothesis WHERE name LIKE 'test_kill_%'")

    id_a = await store.add_hypothesis(name="test_kill_A", description="x",
                                       kill_criteria={}, weight=0.5)
    id_b = await store.add_hypothesis(name="test_kill_B", description="y",
                                       kill_criteria={}, weight=0.5)
    await store.kill_hypothesis_by_id(hypothesis_id=id_a, reason="failed signal")

    portfolio = await store.get_active_portfolio()
    active_names = {h["name"] for h in portfolio}
    assert "test_kill_A" not in active_names
    assert "test_kill_B" in active_names


@pytest.mark.asyncio
async def test_get_active_returns_highest_weight_for_backcompat(pool):
    """Legacy `get_active()` callers get the highest-weight active hypothesis."""
    from clawbot.hypothesis_store import HypothesisStore
    store = HypothesisStore(pool)
    await store.init_schema()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM active_hypothesis WHERE name LIKE 'test_ba_%'")

    await store.add_hypothesis(name="test_ba_low", description="x",
                                kill_criteria={}, weight=0.2)
    await store.add_hypothesis(name="test_ba_high", description="y",
                                kill_criteria={}, weight=0.7)
    active = await store.get_active()
    assert active is not None
    assert active["name"] == "test_ba_high"


@pytest.mark.asyncio
async def test_update_progress_score_persists(pool):
    from clawbot.hypothesis_store import HypothesisStore
    store = HypothesisStore(pool)
    await store.init_schema()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM active_hypothesis WHERE name LIKE 'test_prog_%'")

    hid = await store.add_hypothesis(name="test_prog", description="x",
                                      kill_criteria={}, weight=0.5)
    await store.update_progress_score(hypothesis_id=hid, score=0.65)
    portfolio = await store.get_active_portfolio()
    target = next(h for h in portfolio if h["hypothesis_id"] == hid)
    assert abs(float(target["progress_score"]) - 0.65) < 0.001


@pytest.mark.asyncio
async def test_portfolio_respects_cap(pool):
    """add_hypothesis raises when adding would exceed MAX_ACTIVE_HYPOTHESES."""
    from clawbot.hypothesis_store import HypothesisStore
    store = HypothesisStore(pool, max_active=3)
    await store.init_schema()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM active_hypothesis WHERE name LIKE 'test_cap_%'")

    for i in range(3):
        await store.add_hypothesis(name=f"test_cap_{i}", description="x",
                                    kill_criteria={}, weight=0.33)
    with pytest.raises(RuntimeError, match="portfolio_full"):
        await store.add_hypothesis(name="test_cap_overflow", description="x",
                                    kill_criteria={}, weight=0.1)


@pytest.mark.asyncio
async def test_kill_hypothesis_cascades_to_plans(pool):
    """Killing a hypothesis must cascade its plans to abandoned."""
    from clawbot.hypothesis_store import HypothesisStore
    from clawbot.plan_store import PlanStore
    hyp_store = HypothesisStore(pool)
    plan_store = PlanStore(pool)
    await hyp_store.init_schema()
    await plan_store.init_schema()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM active_hypothesis WHERE name LIKE 'test_csc_%'")
        await conn.execute("DELETE FROM plans WHERE agent_id='test_csc_cmo'")

    hid = await hyp_store.add_hypothesis(
        name="test_csc_h1", description="x", kill_criteria={}, weight=0.5,
    )
    await plan_store.create_plan(
        agent_id="test_csc_cmo", hypothesis="m",
        milestones=[{"hypothesis": "first", "success_criteria": ["c"]}],
        hypothesis_id=hid,
    )
    # Plan is active and linked
    cur = await plan_store.get_current_milestone(agent_id="test_csc_cmo")
    assert cur is not None
    assert cur.status == "active"

    await hyp_store.kill_hypothesis_by_id(hypothesis_id=hid, reason="test")

    # Plan is now abandoned
    cur = await plan_store.get_current_milestone(agent_id="test_csc_cmo")
    assert cur is None  # no longer 'active'
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status FROM plans WHERE agent_id='test_csc_cmo' LIMIT 1"
        )
    assert row["status"] == "abandoned"


@pytest.mark.asyncio
async def test_add_hypothesis_cap_holds_under_concurrent_inserts(pool):
    """Two concurrent add_hypothesis at cap-1 must not both succeed."""
    from clawbot.hypothesis_store import HypothesisStore
    import asyncio
    store = HypothesisStore(pool, max_active=2)
    await store.init_schema()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM active_hypothesis WHERE name LIKE 'test_race_%'")
    # Seed one to put us at cap-1
    await store.add_hypothesis(name="test_race_seed", description="x",
                                kill_criteria={}, weight=0.5)
    # Two concurrent adds — only one should succeed
    async def try_add(name: str) -> str:
        try:
            return await store.add_hypothesis(name=name, description="x",
                                               kill_criteria={}, weight=0.5)
        except RuntimeError as exc:
            return str(exc)
    results = await asyncio.gather(
        try_add("test_race_a"), try_add("test_race_b"),
    )
    successes = [r for r in results if not str(r).startswith("portfolio_full")]
    failures = [r for r in results if str(r).startswith("portfolio_full")]
    assert len(successes) == 1, f"expected 1 success, got {len(successes)}: {results}"
    assert len(failures) == 1
