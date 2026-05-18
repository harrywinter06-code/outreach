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


async def test_capital_cap_fires_at_80_95_100(tmp_path):
    """Three escalation thresholds: 80%, 95%, 100%+ each fire once per UTC day."""
    import sys
    import types
    from unittest.mock import AsyncMock, MagicMock

    escalations: list[dict] = []

    async def fake_publish(topic: str, payload: dict) -> None:
        escalations.append({"topic": topic, "payload": payload})

    bus = MagicMock()
    bus.publish = fake_publish

    m = Monitor(
        redis_url="redis://localhost/0",
        kill_file=tmp_path / "kill.flag",
        capital_weekly_cap_gbp=100.0,
    )
    m._db_pool = MagicMock()
    m.set_bus(bus)

    fake_ledger = MagicMock()
    fake_ledger.current_period_total_gbp = AsyncMock(return_value=105.0)

    fake_module = types.ModuleType("clawbot.capital_ledger")
    fake_module.CapitalLedger = MagicMock(return_value=fake_ledger)
    sys.modules["clawbot.capital_ledger"] = fake_module

    try:
        await m.check_capital_cap_proximity()

        assert len(escalations) == 3
        severities = {e["payload"]["severity"] for e in escalations}
        assert "critical" in severities
        assert "warning" in severities

        await m.check_capital_cap_proximity()
        assert len(escalations) == 3
    finally:
        sys.modules.pop("clawbot.capital_ledger", None)


async def test_capital_cap_80_only_at_85_percent(tmp_path):
    """At 85% usage only the 80% threshold fires; 95% and 100% do not."""
    import sys
    import types
    from unittest.mock import AsyncMock, MagicMock

    escalations: list[dict] = []

    async def fake_publish(topic: str, payload: dict) -> None:
        escalations.append(payload)

    bus = MagicMock()
    bus.publish = fake_publish

    m = Monitor(
        redis_url="redis://localhost/0",
        kill_file=tmp_path / "kill.flag",
        capital_weekly_cap_gbp=100.0,
    )
    m._db_pool = MagicMock()
    m.set_bus(bus)

    fake_ledger = MagicMock()
    fake_ledger.current_period_total_gbp = AsyncMock(return_value=85.0)

    fake_module = types.ModuleType("clawbot.capital_ledger")
    fake_module.CapitalLedger = MagicMock(return_value=fake_ledger)
    sys.modules["clawbot.capital_ledger"] = fake_module

    try:
        await m.check_capital_cap_proximity()
    finally:
        sys.modules.pop("clawbot.capital_ledger", None)

    # 85% usage triggers the 80% threshold only; summary shows the actual fraction.
    assert len(escalations) == 1
    assert "85%" in escalations[0]["summary"]  # actual fraction, not the threshold
