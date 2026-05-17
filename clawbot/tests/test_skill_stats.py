"""Tests for skill_calls telemetry: SkillRegistry.set_stats_db + INSERT after call."""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from contextlib import asynccontextmanager

import pytest

from clawbot.skill_registry import SkillRegistry
from clawbot.skill_ctx import make_noop_ctx

BUILTIN_DIR = Path(__file__).parent.parent / "agents" / "skills" / "_builtin"


def _make_mock_pool() -> MagicMock:
    """Build a mock asyncpg pool whose acquire() works as an async context manager."""
    mock_conn = MagicMock()
    mock_conn.execute = AsyncMock(return_value=None)

    @asynccontextmanager
    async def _acquire():
        yield mock_conn

    mock_pool = MagicMock()
    mock_pool.acquire = _acquire
    return mock_pool, mock_conn


def test_registry_writes_stat_row_after_call():
    """After set_stats_db, calling a skill causes acquire() + conn.execute() for the INSERT."""
    mock_pool, mock_conn = _make_mock_pool()

    reg = SkillRegistry(skills_dir=BUILTIN_DIR)
    reg.discover()
    reg.set_stats_db(mock_pool)

    ctx = make_noop_ctx(caller_id="test-agent", budget_usd=1.0)
    record = asyncio.run(reg.call("time_now", {}, ctx))

    assert record.ok is True
    # conn.execute should have been called with an INSERT statement
    mock_conn.execute.assert_called_once()
    call_args = mock_conn.execute.call_args.args
    assert len(call_args) >= 1
    assert "INSERT" in call_args[0].upper()
    assert "skill_calls" in call_args[0].lower()
