import pytest
from unittest.mock import AsyncMock
from clawbot.agent_registry import AgentRegistry, AgentSpec, EXECUTIVE_IDS


def _spec(**kwargs) -> AgentSpec:
    defaults = dict(
        agent_id="writer-001",
        role="UK Content Writer",
        supervisor="cmo",
        soul_path="agents/writer-001/SOUL.md",
        status="active",
        created_at="2026-05-16T00:00:00+00:00",
        call_interval_s=600,
    )
    defaults.update(kwargs)
    return AgentSpec(**defaults)


@pytest.fixture
def registry():
    r = AgentRegistry(redis_url="redis://localhost/0")
    mock = AsyncMock()
    mock.get = AsyncMock(return_value=None)
    mock.set = AsyncMock()
    mock.sadd = AsyncMock()
    mock.srem = AsyncMock()
    mock.smembers = AsyncMock(return_value=set())
    r._redis = mock
    return r


@pytest.mark.asyncio
async def test_register_stores_agent(registry: AgentRegistry):
    spec = _spec()
    await registry.register(spec)
    registry._r.set.assert_called_once()
    registry._r.sadd.assert_called_once()


@pytest.mark.asyncio
async def test_get_returns_none_when_missing(registry: AgentRegistry):
    registry._r.get = AsyncMock(return_value=None)
    result = await registry.get("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_get_returns_spec_when_present(registry: AgentRegistry):
    spec = _spec()
    registry._r.get = AsyncMock(return_value=spec.to_json())
    result = await registry.get("writer-001")
    assert result is not None
    assert result.agent_id == "writer-001"
    assert result.role == "UK Content Writer"


@pytest.mark.asyncio
async def test_list_active_filters_fired_agents(registry: AgentRegistry):
    active = _spec(agent_id="writer-001", status="active")
    fired = _spec(agent_id="writer-002", status="fired")
    registry._r.smembers = AsyncMock(return_value={"writer-001", "writer-002"})

    async def mock_get(key: str):
        if "writer-001" in key:
            return active.to_json()
        if "writer-002" in key:
            return fired.to_json()
        return None

    registry._r.get = mock_get
    result = await registry.list_active()
    assert len(result) == 1
    assert result[0].agent_id == "writer-001"


@pytest.mark.asyncio
async def test_deregister_raises_for_executives(registry: AgentRegistry):
    for exec_id in EXECUTIVE_IDS:
        with pytest.raises(ValueError, match="Cannot deregister executive"):
            await registry.deregister(exec_id)


@pytest.mark.asyncio
async def test_deregister_marks_fired_and_removes_from_index(registry: AgentRegistry):
    spec = _spec()
    registry._r.get = AsyncMock(return_value=spec.to_json())
    await registry.deregister("writer-001")
    registry._r.srem.assert_called_once()


@pytest.mark.asyncio
async def test_worker_count_excludes_executives(registry: AgentRegistry):
    worker = _spec(agent_id="writer-001", status="active")
    ceo = _spec(agent_id="ceo", role="CEO", supervisor="board", status="active")
    registry._r.smembers = AsyncMock(return_value={"writer-001", "ceo"})

    async def mock_get(key: str):
        if "writer-001" in key:
            return worker.to_json()
        if ":ceo" in key:
            return ceo.to_json()
        return None

    registry._r.get = mock_get
    count = await registry.worker_count()
    assert count == 1


@pytest.mark.asyncio
async def test_agent_spec_roundtrip():
    spec = _spec()
    assert AgentSpec.from_json(spec.to_json()) == spec


def test_is_executive_true_for_ceo():
    assert _spec(agent_id="ceo").is_executive is True


def test_is_executive_false_for_worker():
    assert _spec(agent_id="writer-001").is_executive is False
