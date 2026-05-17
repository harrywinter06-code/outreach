import asyncio
from unittest.mock import AsyncMock, MagicMock
from pathlib import Path
from clawbot.agent_lifecycle import AgentLifecycle


def test_lifecycle_handles_spawn_request(tmp_path: Path):
    registry = MagicMock()
    registry.register = AsyncMock()
    bus = MagicMock()
    workers_dir = tmp_path / "agents" / "workers"

    lifecycle = AgentLifecycle(registry=registry, bus=bus, workers_dir=workers_dir)

    msg = {
        "agent_id": "researcher-abc12345",
        "role": "researcher", "soul_text": "you research things",
        "supervisor": "ceo", "call_interval_s": 600,
    }
    asyncio.run(lifecycle._handle_spawn(msg))

    registry.register.assert_called_once()
    soul_path = workers_dir / "researcher-abc12345" / "SOUL.md"
    assert soul_path.exists()
    assert "you research things" in soul_path.read_text()


def test_lifecycle_handles_fire_request():
    registry = MagicMock()
    registry.deregister = AsyncMock()
    lifecycle = AgentLifecycle(registry=registry, bus=MagicMock(), workers_dir=Path("/tmp"))

    asyncio.run(lifecycle._handle_fire({"agent_id": "researcher-abc", "reason": "test"}))
    registry.deregister.assert_called_once_with("researcher-abc")


def test_lifecycle_rejects_firing_executive():
    registry = MagicMock()
    registry.deregister = AsyncMock()
    lifecycle = AgentLifecycle(registry=registry, bus=MagicMock(), workers_dir=Path("/tmp"))

    asyncio.run(lifecycle._handle_fire({"agent_id": "ceo", "reason": "x"}))
    registry.deregister.assert_not_called()
