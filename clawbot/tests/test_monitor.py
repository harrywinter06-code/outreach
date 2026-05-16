import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from clawbot.monitor import Monitor


def _monitor(kill_file: Path) -> Monitor:
    m = Monitor(redis_url="redis://localhost/0", kill_file=kill_file)
    mock_redis = MagicMock()
    mock_redis.get = AsyncMock(return_value=None)
    m._redis = mock_redis
    return m


def test_kill_switch_inactive_when_no_file(tmp_path):
    m = _monitor(tmp_path / "kill.flag")
    assert m.kill_switch_active() is False


def test_kill_switch_active_when_file_exists(tmp_path):
    kill = tmp_path / "kill.flag"
    kill.write_text("halt", encoding="utf-8")
    m = _monitor(kill)
    assert m.kill_switch_active() is True


@pytest.mark.asyncio
async def test_should_halt_true_when_file_present(tmp_path):
    kill = tmp_path / "kill.flag"
    kill.write_text("halt", encoding="utf-8")
    m = _monitor(kill)
    assert await m.should_halt() is True


@pytest.mark.asyncio
async def test_should_halt_false_when_neither_signal(tmp_path):
    m = _monitor(tmp_path / "kill.flag")
    assert await m.should_halt() is False


def test_kill_file_resolved_from_settings_when_not_supplied(tmp_path, monkeypatch):
    """If caller passes kill_file=None, Monitor pulls from settings.kill_file_path."""
    from clawbot import config

    monkeypatch.setattr(config.settings, "kill_file_path", str(tmp_path / "from-settings.flag"))
    m = Monitor(redis_url="redis://localhost/0")
    assert m._kill_file == Path(tmp_path / "from-settings.flag")
