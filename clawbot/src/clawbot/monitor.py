"""
Runtime monitor: tracks RPM usage, enforces daily spend limit, manages kill switch.

Kill switch is FILE-BASED (survives Redis failures). Redis kill channel is a
secondary faster signal for graceful shutdown.

Capital cap monitoring: publishes operator escalation at 80%, 95%, and 100%+
of weekly cap. Each threshold fires at most once per UTC day.
"""
import json
import logging
import time
from dataclasses import dataclass, asdict
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


KILL_REDIS_KEY = "clawbot:kill"
SPEND_KEY_PREFIX = "clawbot:spend"


@dataclass
class SpendRecord:
    date: str
    usd_total: float
    call_count: int

    def to_json(self) -> str:
        return json.dumps(asdict(self))


class Monitor:
    def __init__(
        self,
        redis_url: str,
        max_daily_spend_usd: float = 5.00,
        kill_file: Path | str | None = None,
        capital_weekly_cap_gbp: float = 0.0,
        db_pool: Any = None,
    ) -> None:
        self._url = redis_url
        self._max_spend = max_daily_spend_usd
        if kill_file is None:
            from clawbot.config import settings
            self._kill_file = Path(settings.kill_file_path)
        else:
            self._kill_file = Path(kill_file)
        self._redis: Any = None
        self._capital_weekly_cap_gbp = capital_weekly_cap_gbp
        self._db_pool = db_pool
        # Per-threshold one-shot-per-day: keys are "80", "95", "100"
        self._capital_warnings_sent: dict[str, str | None] = {
            "80": None, "95": None, "100": None,
        }
        self._bus: Any = None

    async def connect(self) -> None:
        import redis.asyncio as aioredis
        self._redis = await aioredis.from_url(self._url, decode_responses=True)

    async def close(self) -> None:
        if self._redis:
            await self._redis.aclose()

    @property
    def _r(self) -> Any:
        assert self._redis is not None, "call connect() first"
        return self._redis

    def kill_switch_active(self) -> bool:
        return self._kill_file.exists()

    async def kill_switch_active_redis(self) -> bool:
        return bool(await self._r.get(KILL_REDIS_KEY))

    async def should_halt(self) -> bool:
        return self.kill_switch_active() or await self.kill_switch_active_redis()

    async def record_spend(self, usd: float) -> None:
        date = datetime.now(UTC).strftime("%Y-%m-%d")
        key = f"{SPEND_KEY_PREFIX}:{date}"
        await self._r.hincrbyfloat(key, "usd_total", usd)
        await self._r.hincrby(key, "call_count", 1)
        await self._r.expire(key, 86400 * 7)

    async def daily_spend_usd(self) -> float:
        date = datetime.now(UTC).strftime("%Y-%m-%d")
        key = f"{SPEND_KEY_PREFIX}:{date}"
        val = await self._r.hget(key, "usd_total")
        return float(val) if val else 0.0

    async def current_spend_usd(self) -> float:
        return 0.0

    async def spend_limit_reached(self) -> bool:
        return await self.daily_spend_usd() >= self._max_spend

    async def rpm_this_minute(self, provider: str) -> int:
        minute = int(time.time()) // 60
        key = f"clawbot:ratelimit:{provider}:{minute}"
        val = await self._r.get(key)
        return int(val) if val else 0

    async def all_provider_rpm(self, provider_names: list[str]) -> dict[str, int]:
        return {p: await self.rpm_this_minute(p) for p in provider_names}

    def set_bus(self, bus: Any) -> None:
        self._bus = bus

    async def check_capital_cap_proximity(self) -> None:
        """Check capital usage against 80%, 95%, and 100%+ of weekly cap.

        Each threshold fires at most one escalation per UTC day.
        """
        if self._db_pool is None or self._capital_weekly_cap_gbp <= 0:
            return
        try:
            from clawbot.capital_ledger import CapitalLedger
            today_str = datetime.now(UTC).date().isoformat()
            led = CapitalLedger(self._db_pool)
            weekly_spent = await led.current_period_total_gbp(
                period_hours=168, live_only=True,
            )
            fraction = float(weekly_spent) / float(self._capital_weekly_cap_gbp)
            for threshold, severity in [
                (1.00, "critical"), (0.95, "warning"), (0.80, "warning"),
            ]:
                key = str(int(threshold * 100))
                if fraction >= threshold and self._capital_warnings_sent.get(key) != today_str:
                    if self._bus is not None:
                        await self._bus.publish("operator.escalation", {
                            "severity": severity,
                            "summary": (
                                f"Capital usage at {fraction*100:.0f}% of weekly cap "
                                f"(£{float(weekly_spent):.2f} / £{self._capital_weekly_cap_gbp:.2f})"
                            ),
                            "detail": (
                                "Set CAPITAL_FREEZE=true in .env to halt authorizations, "
                                "or wait for the weekly window to roll over."
                            ),
                            "source": "monitor",
                        })
                    self._capital_warnings_sent[key] = today_str
        except Exception as exc:
            logger.warning("Capital cap proximity check failed: %s", exc)
