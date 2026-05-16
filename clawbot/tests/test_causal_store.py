"""Tests for CausalStore and CAG database schema."""
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mock_pool():
    pool = MagicMock()
    pool.execute = AsyncMock()
    pool.fetch = AsyncMock(return_value=[])
    pool.fetchval = AsyncMock(return_value=None)
    conn = MagicMock()
    conn.execute = AsyncMock()
    conn.transaction = MagicMock()
    conn.transaction.return_value.__aenter__ = AsyncMock(return_value=None)
    conn.transaction.return_value.__aexit__ = AsyncMock(return_value=None)
    pool.acquire = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
    pool._conn = conn  # expose for assertions
    return pool


async def test_db_init_schema_creates_causal_chain_table():
    from clawbot.db import Database
    db = Database("postgresql://test/test")
    db._pool = MagicMock()
    db._pool.execute = AsyncMock()

    await db.init_schema()

    calls = [str(c) for c in db._pool.execute.call_args_list]
    assert any("causal_chain" in c for c in calls)


async def test_db_init_schema_creates_product_causal_map_table():
    from clawbot.db import Database
    db = Database("postgresql://test/test")
    db._pool = MagicMock()
    db._pool.execute = AsyncMock()

    await db.init_schema()

    calls = [str(c) for c in db._pool.execute.call_args_list]
    assert any("product_causal_map" in c for c in calls)


async def test_record_event_returns_event_id(mock_pool):
    mock_pool.fetchval = AsyncMock(return_value=str(uuid.uuid4()))
    from clawbot.causal_store import CausalStore
    store = CausalStore(mock_pool)
    event_id = await store.record_event(
        chain_id=str(uuid.uuid4()),
        agent_id="ceo",
        action_type="directive",
        causal_depth=0,
    )
    assert event_id is not None
    assert len(event_id) == 36  # UUID string


async def test_close_chain_distributes_revenue_inversely_by_depth(mock_pool):
    chain_id = str(uuid.uuid4())
    event_id_0 = str(uuid.uuid4())
    event_id_1 = str(uuid.uuid4())

    mock_pool.fetch = AsyncMock(return_value=[
        {"event_id": event_id_0, "causal_depth": 0},
        {"event_id": event_id_1, "causal_depth": 1},
    ])

    from clawbot.causal_store import CausalStore
    store = CausalStore(mock_pool)
    await store.close_chain(chain_id, revenue_gbp=9.0)

    conn = mock_pool._conn
    calls = conn.execute.call_args_list
    # depth=0 weight=1.0, depth=1 weight=0.5 → total=1.5
    # depth=0 share = 9.0 * (1.0/1.5) = 6.0
    # depth=1 share = 9.0 * (0.5/1.5) = 3.0
    shares = [c.args[1] for c in calls]
    assert abs(shares[0] - 6.0) < 0.01
    assert abs(shares[1] - 3.0) < 0.01


async def test_close_chain_noops_when_no_open_events(mock_pool):
    mock_pool.fetch = AsyncMock(return_value=[])
    from clawbot.causal_store import CausalStore
    store = CausalStore(mock_pool)
    # Should not raise
    await store.close_chain(str(uuid.uuid4()), revenue_gbp=10.0)
    mock_pool._conn.execute.assert_not_called()


async def test_attributed_revenue_7d_sums_closed_events(mock_pool):
    mock_pool.fetchval = AsyncMock(return_value=42.5)
    from clawbot.causal_store import CausalStore
    store = CausalStore(mock_pool)
    result = await store.attributed_revenue_7d("ceo")
    assert result == pytest.approx(42.5)


async def test_attributed_revenue_7d_returns_zero_on_none(mock_pool):
    mock_pool.fetchval = AsyncMock(return_value=None)
    from clawbot.causal_store import CausalStore
    store = CausalStore(mock_pool)
    result = await store.attributed_revenue_7d("unknown-agent")
    assert result == 0.0


async def test_register_product_calls_execute(mock_pool):
    chain_id = str(uuid.uuid4())
    from clawbot.causal_store import CausalStore
    store = CausalStore(mock_pool)
    await store.register_product("prod_abc", chain_id, "UK Tax Guide 2026")
    mock_pool.execute.assert_called_once()
    call_sql = mock_pool.execute.call_args.args[0]
    assert "product_causal_map" in call_sql


async def test_product_chain_id_returns_stored_value(mock_pool):
    chain_id = str(uuid.uuid4())
    mock_pool.fetchval = AsyncMock(return_value=chain_id)
    from clawbot.causal_store import CausalStore
    store = CausalStore(mock_pool)
    result = await store.product_chain_id("prod_abc")
    assert result == chain_id


async def test_product_chain_id_returns_none_when_missing(mock_pool):
    mock_pool.fetchval = AsyncMock(return_value=None)
    from clawbot.causal_store import CausalStore
    store = CausalStore(mock_pool)
    result = await store.product_chain_id("unknown_product")
    assert result is None
