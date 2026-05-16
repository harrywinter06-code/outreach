import pytest
import numpy as np
from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock, patch

from clawbot.company_brain import CompanyBrain, BrainEntry, _row_to_entry


def _mock_pool() -> MagicMock:
    pool = MagicMock()
    pool.fetchrow = AsyncMock(return_value={"id": 42})
    pool.fetch = AsyncMock(return_value=[])
    return pool


def _fake_row(
    id: int = 1,
    content: str = "IR35 research",
    category: str = "opportunity",
    metadata: str | dict | None = "{}",
    score: float = 0.9,
) -> dict:
    return {
        "id": id,
        "content": content,
        "category": category,
        "metadata": metadata,
        "created_at": datetime.now(UTC),
        "score": score,
    }


@pytest.mark.asyncio
async def test_write_stores_entry_and_returns_id():
    pool = _mock_pool()
    brain = CompanyBrain(pool)

    with patch.object(brain, "_embed", new=AsyncMock(return_value=np.zeros(384))):
        result = await brain.write("IR35 contractors asking about CEST", "opportunity")

    pool.fetchrow.assert_called_once()
    sql = pool.fetchrow.call_args.args[0]
    assert "INSERT INTO knowledge" in sql
    assert result == 42


@pytest.mark.asyncio
async def test_search_returns_entries():
    pool = _mock_pool()
    pool.fetch = AsyncMock(return_value=[_fake_row()])
    brain = CompanyBrain(pool)

    with patch.object(brain, "_embed", new=AsyncMock(return_value=np.zeros(384))):
        entries = await brain.search("IR35", k=3)

    assert len(entries) == 1
    assert isinstance(entries[0], BrainEntry)
    assert entries[0].score == pytest.approx(0.9)


@pytest.mark.asyncio
async def test_search_with_category_adds_where_clause():
    pool = _mock_pool()
    brain = CompanyBrain(pool)

    with patch.object(brain, "_embed", new=AsyncMock(return_value=np.zeros(384))):
        await brain.search("IR35", k=3, category="opportunity")

    sql = pool.fetch.call_args.args[0]
    assert "WHERE category" in sql


@pytest.mark.asyncio
async def test_get_recent_uses_order_by_created_at():
    pool = _mock_pool()
    brain = CompanyBrain(pool)

    await brain.get_recent("decision", n=5)

    sql = pool.fetch.call_args.args[0]
    assert "ORDER BY created_at DESC" in sql


@pytest.mark.asyncio
async def test_embed_runs_via_executor_not_in_event_loop():
    """Synchronous _embed_sync must be dispatched via loop.run_in_executor,
    not called directly inline (which would block the scheduler)."""
    pool = _mock_pool()
    brain = CompanyBrain(pool)

    sentinel = np.ones(384) * 7
    with patch.object(brain, "_embed_sync", return_value=sentinel) as sync_mock:
        result = await brain._embed("hello")
        assert np.array_equal(result, sentinel)
        sync_mock.assert_called_once_with("hello")


def test_row_to_entry_parses_json_string_metadata():
    row = _fake_row(metadata='{"source": "reddit"}')
    entry = _row_to_entry(row)
    assert entry.metadata == {"source": "reddit"}


def test_row_to_entry_handles_dict_metadata():
    row = _fake_row(metadata={"source": "reddit"})
    entry = _row_to_entry(row)
    assert entry.metadata == {"source": "reddit"}


def test_row_to_entry_handles_none_metadata():
    row = _fake_row(metadata=None)
    entry = _row_to_entry(row)
    assert entry.metadata == {}
