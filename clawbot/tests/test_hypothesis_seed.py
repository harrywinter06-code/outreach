"""Startup seed inserts the initial hypothesis only when no hypothesis is active yet."""
import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

# Patch asyncpg before importing main to avoid heavy load
sys.modules["asyncpg"] = MagicMock()

from clawbot.main import maybe_seed_initial_hypothesis


def test_seed_only_when_store_empty():
    store = MagicMock()
    store.get_active = AsyncMock(return_value=None)
    store.set_active = AsyncMock(return_value="hyp_seed")
    result = asyncio.run(maybe_seed_initial_hypothesis(store))
    assert result is True
    store.set_active.assert_called_once()


def test_seed_skipped_when_active_exists():
    store = MagicMock()
    store.get_active = AsyncMock(return_value={"name": "H1", "status": "active"})
    store.set_active = AsyncMock()
    result = asyncio.run(maybe_seed_initial_hypothesis(store))
    assert result is False
    store.set_active.assert_not_called()
