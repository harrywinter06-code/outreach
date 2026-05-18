"""active_hypothesis table CRUD — only one row active at a time."""
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
async def test_init_schema_creates_table(pool):
    from clawbot.hypothesis_store import HypothesisStore
    store = HypothesisStore(pool)
    await store.init_schema()


@pytest.mark.asyncio
async def test_set_active_marks_previous_superseded(pool):
    from clawbot.hypothesis_store import HypothesisStore
    store = HypothesisStore(pool)
    await store.init_schema()
    await store.set_active(name="H1", description="£9 IR35 PDF",
                            kill_criteria={"max_days_without_revenue": 14})
    await store.set_active(name="H2", description="B2B research briefs",
                            kill_criteria={"max_days_without_revenue": 21})
    active = await store.get_active()
    assert active is not None
    assert active["name"] == "H2"
    history = await store.list_history()
    assert any(h["name"] == "H1" and h["status"] == "superseded" for h in history)


@pytest.mark.asyncio
async def test_kill_active_clears_active_row(pool):
    from clawbot.hypothesis_store import HypothesisStore
    store = HypothesisStore(pool)
    await store.init_schema()
    await store.set_active(name="H1", description="x", kill_criteria={})
    await store.kill_active(reason="0 conversions by day 14")
    assert await store.get_active() is None
