"""
Homeostasis — control-loop throttles on rates of change.

The fundamental failure mode of an evolving system is *variation rate outrunning
selection signal*: mutations stack faster than fitness can be measured, the
gradient becomes noise, and the system thrashes through runway without learning.
Biology's equivalent is thermoregulation — a setpoint and an autonomic response
to breaches. We do the same for the rates we control.

Setpoints (rolling 7-day windows):
- mutations_per_week: ≤ 7 (one per day on average)
- agents_spawned_per_week: ≤ 5
- agents_fired_per_week: ≤ 5

Counters are stored in Redis sorted sets (ZADD with timestamp scores) so the
window can be queried with ZCOUNT and trimmed with ZREMRANGEBYSCORE. Multi-
container safe — multiple agents recording events arrive at consistent counts.

The scheduler / evolution / agent_factory consult `allowed(kind)` before acting.
If the breach is silent (no LLM call needed), the throttle is free.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any


WINDOW_S = 7 * 86_400  # 7-day rolling window
KEY_PREFIX = "clawbot:homeostasis"


@dataclass(frozen=True)
class Setpoint:
    kind: str
    max_per_window: int


DEFAULT_SETPOINTS: dict[str, Setpoint] = {
    "mutations": Setpoint("mutations", max_per_window=7),
    "agents_spawned": Setpoint("agents_spawned", max_per_window=5),
    "agents_fired": Setpoint("agents_fired", max_per_window=5),
}


class Homeostasis:
    """Rolling-window event counter with allow/deny based on configured setpoints."""

    def __init__(
        self,
        redis_url: str | None = None,
        setpoints: dict[str, Setpoint] | None = None,
    ) -> None:
        self._url = redis_url
        self._setpoints = setpoints or DEFAULT_SETPOINTS
        self._redis: Any = None
        # In-memory fallback for tests / no-Redis environments
        self._mem: dict[str, list[float]] = {}

    async def connect(self) -> None:
        if self._url is None:
            return
        import redis.asyncio as aioredis
        self._redis = await aioredis.from_url(self._url, decode_responses=True)

    async def close(self) -> None:
        if self._redis:
            await self._redis.aclose()

    def _key(self, kind: str) -> str:
        return f"{KEY_PREFIX}:{kind}"

    async def record_event(self, kind: str) -> int:
        """Record one event of this kind. Returns the new count in the window.

        Member uniqueness is provided by uuid4 — id(object()) can reuse a value
        within the same process and silently dedupe via ZADD's set semantics,
        under-reporting concurrent event counts.
        """
        now = time.time()
        if self._redis is not None:
            key = self._key(kind)
            member = f"{now}:{uuid.uuid4().hex}"
            await self._redis.zadd(key, {member: now})
            await self._redis.zremrangebyscore(key, 0, now - WINDOW_S)
            await self._redis.expire(key, WINDOW_S + 3600)
            count = await self._redis.zcount(key, now - WINDOW_S, "+inf")
            return int(count)
        # in-memory fallback
        bucket = self._mem.setdefault(kind, [])
        bucket.append(now)
        cutoff = now - WINDOW_S
        bucket[:] = [t for t in bucket if t >= cutoff]
        return len(bucket)

    async def count_in_window(self, kind: str) -> int:
        now = time.time()
        if self._redis is not None:
            return int(await self._redis.zcount(self._key(kind), now - WINDOW_S, "+inf"))
        bucket = self._mem.get(kind, [])
        cutoff = now - WINDOW_S
        return sum(1 for t in bucket if t >= cutoff)

    async def allowed(self, kind: str) -> bool:
        """True if recording one more event would not exceed the setpoint.

        Caller pattern: `if not await homeostasis.allowed("mutations"): return`
        Then if proceeding, call `record_event(kind)` after the action.
        """
        setpoint = self._setpoints.get(kind)
        if setpoint is None:
            return True  # unconfigured → no throttle
        current = await self.count_in_window(kind)
        return current < setpoint.max_per_window

    async def remaining(self, kind: str) -> int:
        """How many more events of this kind are allowed in the current window."""
        setpoint = self._setpoints.get(kind)
        if setpoint is None:
            return 1_000_000
        current = await self.count_in_window(kind)
        return max(0, setpoint.max_per_window - current)

    def configured_setpoints(self) -> dict[str, Setpoint]:
        return dict(self._setpoints)
