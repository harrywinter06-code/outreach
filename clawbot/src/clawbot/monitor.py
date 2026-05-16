"""
Runtime monitor: tracks RPM usage, enforces daily spend limit, manages kill switch.

Kill switch is FILE-BASED — agents poll a path on disk each loop iteration.
This survives Redis failures and cannot be blocked by a misbehaving agent that
holds a Redis lock. The file is created by a human (or a Fly.io cron writing to
a mounted volume) and deleted to resume.

Redis kill channel is a secondary, faster signal for graceful shutdown.
"""
import json
import time
from dataclasses import dataclass, asdict
from datetime import datetime, UTC
from pathlib import Path
from typing import Any


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
    ) -> None:
        self._url = redis_url
        self._max_spend = max_daily_spend_usd
        # Resolve from settings if caller didn't supply one. Tests pass an explicit
        # tmp_path to avoid touching the host /tmp.
        if kill_file is None:
            from clawbot.config import settings
            self._kill_file = Path(settings.kill_file_path)
        else:
            self._kill_file = Path(kill_file)
        self._redis: Any = None

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
        """File-based check — safe even if Redis is down."""
        return self._kill_file.exists()

    async def kill_switch_active_redis(self) -> bool:
        """Secondary Redis-based check for graceful in-process shutdown."""
        return bool(await self._r.get(KILL_REDIS_KEY))

    async def should_halt(self) -> bool:
        """True if any kill signal is active."""
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
        """Return current daily spend. Returns 0.0 if tracking not implemented."""
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
