import pytest

from clawbot.homeostasis import Homeostasis, Setpoint, DEFAULT_SETPOINTS


@pytest.mark.asyncio
async def test_in_memory_record_increments_count():
    h = Homeostasis(redis_url=None)
    assert await h.count_in_window("mutations") == 0
    await h.record_event("mutations")
    await h.record_event("mutations")
    assert await h.count_in_window("mutations") == 2


@pytest.mark.asyncio
async def test_allowed_true_when_below_setpoint():
    h = Homeostasis(redis_url=None)
    assert await h.allowed("mutations") is True


@pytest.mark.asyncio
async def test_allowed_false_when_at_setpoint():
    h = Homeostasis(redis_url=None, setpoints={"mutations": Setpoint("mutations", max_per_window=3)})
    for _ in range(3):
        await h.record_event("mutations")
    assert await h.allowed("mutations") is False


@pytest.mark.asyncio
async def test_remaining_decrements_with_events():
    h = Homeostasis(redis_url=None, setpoints={"mutations": Setpoint("mutations", max_per_window=5)})
    assert await h.remaining("mutations") == 5
    await h.record_event("mutations")
    await h.record_event("mutations")
    assert await h.remaining("mutations") == 3


@pytest.mark.asyncio
async def test_unknown_kind_is_always_allowed():
    """Unconfigured kinds default to no throttle — caller's responsibility to add a setpoint."""
    h = Homeostasis(redis_url=None)
    assert await h.allowed("unknown_kind") is True
    assert await h.remaining("unknown_kind") > 1000


@pytest.mark.asyncio
async def test_default_setpoints_present():
    assert "mutations" in DEFAULT_SETPOINTS
    assert "agents_spawned" in DEFAULT_SETPOINTS
    assert "agents_fired" in DEFAULT_SETPOINTS


@pytest.mark.asyncio
async def test_kinds_are_isolated():
    """Recording mutations should not affect agents_spawned counter."""
    h = Homeostasis(redis_url=None)
    for _ in range(5):
        await h.record_event("mutations")
    assert await h.count_in_window("mutations") == 5
    assert await h.count_in_window("agents_spawned") == 0


@pytest.mark.asyncio
async def test_configured_setpoints_returns_copy():
    """Defensive copy — caller can't mutate internal state."""
    h = Homeostasis(redis_url=None)
    snap = h.configured_setpoints()
    snap.clear()
    assert "mutations" in h.configured_setpoints()


@pytest.mark.asyncio
async def test_rapid_concurrent_record_events_all_counted():
    """uuid uniquifier prevents ZADD member collisions when events fire in
    the same microsecond. Without it, id(object()) reuse can silently dedupe."""
    from unittest.mock import AsyncMock
    fake_redis = AsyncMock()
    fake_redis.zadd = AsyncMock()
    fake_redis.zremrangebyscore = AsyncMock()
    fake_redis.expire = AsyncMock()
    fake_redis.zcount = AsyncMock(return_value=10)

    h = Homeostasis(redis_url=None)
    h._redis = fake_redis

    # Issue 5 concurrent records of the same kind
    import asyncio
    await asyncio.gather(*[h.record_event("mutations") for _ in range(5)])

    members_seen: set[str] = set()
    for call in fake_redis.zadd.call_args_list:
        member_dict = call.args[1]
        members_seen.update(member_dict.keys())
    assert len(members_seen) == 5, "uuid should make every member unique"
