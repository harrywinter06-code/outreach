"""Capital ledger CRUD + cap enforcement queries."""
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
    from clawbot.capital_ledger import CapitalLedger
    led = CapitalLedger(pool)
    await led.init_schema()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='capital_ledger' ORDER BY column_name"
        )
    cols = {r["column_name"] for r in rows}
    assert {"entry_id", "agent_id", "action_type", "amount_gbp", "is_live_mode"} <= cols


@pytest.mark.asyncio
async def test_record_and_query_total(pool):
    from clawbot.capital_ledger import CapitalLedger
    from decimal import Decimal
    led = CapitalLedger(pool)
    await led.init_schema()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM capital_ledger WHERE agent_id LIKE 'test_%'")
    await led.record(agent_id="test_cfo", action_type="card_issued",
                     amount_gbp=Decimal("25.00"), is_live_mode=True)
    await led.record(agent_id="test_cfo", action_type="charge_authorized",
                     amount_gbp=Decimal("12.50"), is_live_mode=True)
    await led.record(agent_id="test_cfo", action_type="refund_processed",
                     amount_gbp=Decimal("-5.00"), is_live_mode=True)
    total_24h = await led.current_period_total_gbp(period_hours=24, live_only=True)
    assert total_24h == Decimal("32.50")


@pytest.mark.asyncio
async def test_test_mode_excluded_from_live_total(pool):
    from clawbot.capital_ledger import CapitalLedger
    from decimal import Decimal
    led = CapitalLedger(pool)
    await led.init_schema()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM capital_ledger WHERE agent_id LIKE 'test2_%'")
    await led.record(agent_id="test2_cfo", action_type="card_issued",
                     amount_gbp=Decimal("100.00"), is_live_mode=False)
    await led.record(agent_id="test2_cfo", action_type="card_issued",
                     amount_gbp=Decimal("50.00"), is_live_mode=True)
    live_total = await led.current_period_total_gbp(period_hours=24, live_only=True)
    assert live_total == Decimal("50.00")


@pytest.mark.asyncio
async def test_period_window_filters_correctly(pool):
    """Older entries outside the window are excluded."""
    from clawbot.capital_ledger import CapitalLedger
    from decimal import Decimal
    led = CapitalLedger(pool)
    await led.init_schema()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM capital_ledger WHERE agent_id LIKE 'test3_%'")
        await conn.execute(
            "INSERT INTO capital_ledger (agent_id, action_type, amount_gbp, is_live_mode, created_at) "
            "VALUES ($1, $2, $3, $4, NOW() - INTERVAL '8 days')",
            "test3_cfo", "card_issued", Decimal("999.00"), True,
        )
    await led.record(agent_id="test3_cfo", action_type="card_issued",
                     amount_gbp=Decimal("10.00"), is_live_mode=True)
    weekly = await led.current_period_total_gbp(period_hours=168, live_only=True)
    assert weekly == Decimal("10.00")
