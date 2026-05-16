"""Scheduler tests: skeleton-crew gating, dynamic-agent sync, metrics writer."""
import asyncio
import json
import pytest
from datetime import datetime, UTC
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from clawbot.agent_registry import AgentSpec
from clawbot.scheduler import Scheduler, _is_skeleton_crew_hour


# ── Skeleton-crew gate ──────────────────────────────────────────────────────


def test_skeleton_crew_active_at_23_00_utc():
    assert _is_skeleton_crew_hour(datetime(2026, 5, 16, 23, 30, tzinfo=UTC)) is True


def test_skeleton_crew_active_at_03_00_utc():
    assert _is_skeleton_crew_hour(datetime(2026, 5, 16, 3, 0, tzinfo=UTC)) is True


def test_skeleton_crew_inactive_at_12_00_utc():
    assert _is_skeleton_crew_hour(datetime(2026, 5, 16, 12, 0, tzinfo=UTC)) is False


def test_skeleton_crew_boundary_06_00_inactive():
    """06:00 marks the end of skeleton crew — peak hours resume."""
    assert _is_skeleton_crew_hour(datetime(2026, 5, 16, 6, 0, tzinfo=UTC)) is False


def test_skeleton_crew_boundary_22_59_inactive():
    assert _is_skeleton_crew_hour(datetime(2026, 5, 16, 22, 59, tzinfo=UTC)) is False


# ── Dynamic agent sync ──────────────────────────────────────────────────────


def _spec(agent_id: str, soul_path: str = "agents/x/SOUL.md") -> AgentSpec:
    return AgentSpec(
        agent_id=agent_id, role="writer", supervisor="cmo",
        soul_path=soul_path, status="active",
        created_at=datetime.now(UTC).isoformat(),
        call_interval_s=600,
    )


def _scheduler(tmp_path: Path, registry: MagicMock | None = None) -> Scheduler:
    pool = MagicMock()
    pool.complete = AsyncMock(return_value='{"x":1}')
    bus = MagicMock()
    bus.publish = AsyncMock()
    bus.subscribe = AsyncMock()
    monitor = MagicMock()
    monitor.should_halt = AsyncMock(return_value=False)
    monitor.spend_limit_reached = AsyncMock(return_value=False)
    return Scheduler(
        pool=pool, bus=bus, monitor=monitor,
        registry=registry,
        agents_dir=tmp_path / "agents",
        metrics_dir=tmp_path / "metrics",
    )


@pytest.mark.asyncio
async def test_sync_starts_task_for_newly_registered_worker(tmp_path):
    spec = _spec("writer-001")
    registry = MagicMock()
    registry.list_active = AsyncMock(return_value=[spec])
    scheduler = _scheduler(tmp_path, registry=registry)

    await scheduler._sync_dynamic_agents()

    assert "writer-001" in scheduler._agent_tasks
    scheduler._agent_tasks["writer-001"].cancel()


@pytest.mark.asyncio
async def test_sync_cancels_task_for_fired_worker(tmp_path):
    spec = _spec("writer-001")
    registry = MagicMock()
    registry.list_active = AsyncMock(return_value=[spec])
    scheduler = _scheduler(tmp_path, registry=registry)

    await scheduler._sync_dynamic_agents()
    task = scheduler._agent_tasks["writer-001"]

    # Fire the worker
    registry.list_active = AsyncMock(return_value=[])
    await scheduler._sync_dynamic_agents()

    assert "writer-001" not in scheduler._agent_tasks
    await asyncio.sleep(0)  # let the cancellation propagate
    assert task.cancelled() or task.done()


@pytest.mark.asyncio
async def test_sync_skips_executives(tmp_path):
    """Executives have their own dedicated _executive_loop — don't double-run."""
    exec_spec = AgentSpec(
        agent_id="ceo", role="CEO", supervisor="board",
        soul_path="agents/ceo/SOUL.md", status="active",
        created_at=datetime.now(UTC).isoformat(),
    )
    registry = MagicMock()
    registry.list_active = AsyncMock(return_value=[exec_spec])
    scheduler = _scheduler(tmp_path, registry=registry)

    await scheduler._sync_dynamic_agents()

    assert "ceo" not in scheduler._agent_tasks


@pytest.mark.asyncio
async def test_sync_is_idempotent_for_already_running_worker(tmp_path):
    spec = _spec("writer-001")
    registry = MagicMock()
    registry.list_active = AsyncMock(return_value=[spec])
    scheduler = _scheduler(tmp_path, registry=registry)

    await scheduler._sync_dynamic_agents()
    first_task = scheduler._agent_tasks["writer-001"]
    await scheduler._sync_dynamic_agents()
    second_task = scheduler._agent_tasks["writer-001"]

    assert first_task is second_task
    first_task.cancel()


# ── Metrics writer ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_metrics_writer_creates_company_metrics_file(tmp_path, monkeypatch):
    monkeypatch.setattr("clawbot.scheduler.settings.gumroad_api_key", "")
    scheduler = _scheduler(tmp_path)

    await scheduler._write_company_metrics()

    metrics_file = tmp_path / "metrics" / "company_metrics.json"
    assert metrics_file.exists()
    data = json.loads(metrics_file.read_text())
    assert "revenue_7d_gbp" in data
    assert "worker_count" in data
    assert "timestamp" in data
    assert data["revenue_7d_gbp"] == 0.0  # no gumroad key → no revenue


@pytest.mark.asyncio
async def test_metrics_writer_reads_revenue_from_gumroad_when_key_present(tmp_path, monkeypatch):
    monkeypatch.setattr("clawbot.scheduler.settings.gumroad_api_key", "test-key")

    class FakeGumroad:
        def __init__(self, api_key):
            pass
        async def sales_last_7_days_gbp(self):
            return 27.50

    monkeypatch.setattr("clawbot.gumroad.GumroadClient", FakeGumroad)
    scheduler = _scheduler(tmp_path)

    await scheduler._write_company_metrics()

    data = json.loads((tmp_path / "metrics" / "company_metrics.json").read_text())
    assert data["revenue_7d_gbp"] == 27.50


@pytest.mark.asyncio
async def test_metrics_writer_tolerates_gumroad_failure(tmp_path, monkeypatch):
    monkeypatch.setattr("clawbot.scheduler.settings.gumroad_api_key", "test-key")

    class BrokenGumroad:
        def __init__(self, api_key):
            pass
        async def sales_last_7_days_gbp(self):
            raise RuntimeError("API down")

    monkeypatch.setattr("clawbot.gumroad.GumroadClient", BrokenGumroad)
    scheduler = _scheduler(tmp_path)

    await scheduler._write_company_metrics()  # must not raise

    data = json.loads((tmp_path / "metrics" / "company_metrics.json").read_text())
    assert data["revenue_7d_gbp"] == 0.0
