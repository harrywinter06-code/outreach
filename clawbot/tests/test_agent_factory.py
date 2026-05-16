import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from clawbot.agent_factory import AgentFactory, _make_id
from clawbot.agent_registry import AgentRegistry, AgentSpec


def _mock_registry(worker_count: int = 0) -> AgentRegistry:
    registry = MagicMock(spec=AgentRegistry)
    registry.worker_count = AsyncMock(return_value=worker_count)
    registry.register = AsyncMock()
    registry.get = AsyncMock(return_value=None)
    registry.deregister = AsyncMock()
    return registry


def _mock_pool(response: str = "## IMMUTABLE\n\nTest soul.\n\n## MUTABLE\n\n### current_focus\nNone.") -> MagicMock:
    pool = MagicMock()
    pool.complete = AsyncMock(return_value=response)
    return pool


@pytest.mark.asyncio
async def test_spawn_creates_soul_file(tmp_path):
    registry = _mock_registry(worker_count=0)
    factory = AgentFactory(registry=registry, agents_dir=tmp_path, max_workers=20)
    pool = _mock_pool()

    spec = await factory.spawn(
        role="UK Content Writer",
        supervisor="cmo",
        mandate="Write Reddit posts that drive Gumroad sales.",
        pool=pool,
    )

    soul_path = tmp_path / spec.agent_id / "SOUL.md"
    assert soul_path.exists()
    assert "## IMMUTABLE" in soul_path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_spawn_registers_agent(tmp_path):
    registry = _mock_registry(worker_count=0)
    factory = AgentFactory(registry=registry, agents_dir=tmp_path, max_workers=20)

    await factory.spawn("UK Researcher", "ceo", "Find opportunities.", pool=_mock_pool())

    registry.register.assert_called_once()
    registered_spec = registry.register.call_args.args[0]
    assert registered_spec.supervisor == "ceo"
    assert registered_spec.status == "active"


@pytest.mark.asyncio
async def test_spawn_raises_at_worker_cap(tmp_path):
    registry = _mock_registry(worker_count=20)
    factory = AgentFactory(registry=registry, agents_dir=tmp_path, max_workers=20)

    with pytest.raises(RuntimeError, match="Worker cap reached"):
        await factory.spawn("Writer", "cmo", "Write stuff.", pool=_mock_pool())


@pytest.mark.asyncio
async def test_fire_archives_soul_file(tmp_path):
    soul_path = tmp_path / "writer-001" / "SOUL.md"
    soul_path.parent.mkdir(parents=True)
    soul_path.write_text("## IMMUTABLE\nOld soul.", encoding="utf-8")

    spec = AgentSpec(
        agent_id="writer-001", role="Writer", supervisor="cmo",
        soul_path=str(soul_path), status="active",
        created_at="2026-01-01T00:00:00+00:00",
    )
    registry = _mock_registry()
    registry.get = AsyncMock(return_value=spec)

    factory = AgentFactory(registry=registry, agents_dir=tmp_path)
    await factory.fire("writer-001")

    assert not soul_path.exists()
    archived = list(soul_path.parent.glob("*.fired-*.md"))
    assert len(archived) == 1


@pytest.mark.asyncio
async def test_fire_deregisters_agent(tmp_path):
    spec = AgentSpec(
        agent_id="writer-001", role="Writer", supervisor="cmo",
        soul_path=str(tmp_path / "writer-001" / "SOUL.md"), status="active",
        created_at="2026-01-01T00:00:00+00:00",
    )
    registry = _mock_registry()
    registry.get = AsyncMock(return_value=spec)

    factory = AgentFactory(registry=registry, agents_dir=tmp_path)
    await factory.fire("writer-001")

    registry.deregister.assert_called_once_with("writer-001")


@pytest.mark.asyncio
async def test_fire_noop_when_agent_not_found(tmp_path):
    registry = _mock_registry()
    registry.get = AsyncMock(return_value=None)
    factory = AgentFactory(registry=registry, agents_dir=tmp_path)
    await factory.fire("nonexistent")  # should not raise


def test_make_id_slugifies_role():
    assert _make_id("UK Content Writer", 1) == "uk-content-writer-001"
    assert _make_id("IR35 Researcher!", 12) == "ir35-researcher-012"


def test_daily_budget_calculation():
    factory = AgentFactory(registry=_mock_registry(), agents_dir=Path("."))
    assert factory.daily_budget_for_n_workers(5) == 5 * 144
