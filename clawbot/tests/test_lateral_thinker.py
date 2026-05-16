import time
import pytest
from unittest.mock import AsyncMock, MagicMock


async def test_lateral_thinker_skips_when_too_few_signals():
    from clawbot.lateral_thinker import LateralThinker, MIN_SIGNALS

    brain = MagicMock()
    brain.search = AsyncMock(return_value=[])
    brain.write = AsyncMock()
    pool = MagicMock()
    pool.complete = AsyncMock()

    thinker = LateralThinker(pool=pool, brain=brain)
    result = await thinker.synthesise()

    assert result is None
    pool.complete.assert_not_called()
    brain.write.assert_not_called()


async def test_lateral_thinker_skips_stale_signals():
    from clawbot.lateral_thinker import LateralThinker, FRESHNESS_DAYS

    stale_ts = time.time() - (FRESHNESS_DAYS + 2) * 86400

    class FakeEntry:
        content = "old opportunity"
        metadata = {"ts": stale_ts}

    brain = MagicMock()
    brain.search = AsyncMock(return_value=[FakeEntry()] * 5)
    brain.write = AsyncMock()
    pool = MagicMock()
    pool.complete = AsyncMock()

    thinker = LateralThinker(pool=pool, brain=brain)
    result = await thinker.synthesise()

    assert result is None
    pool.complete.assert_not_called()


async def test_lateral_thinker_synthesises_fresh_signals():
    from clawbot.lateral_thinker import LateralThinker, MIN_SIGNALS

    fresh_ts = time.time() - 86400  # 1 day ago

    class FakeEntry:
        def __init__(self, i):
            self.content = f"Opportunity {i}: UK tax planning tool"
            self.metadata = {"ts": fresh_ts}

    brain = MagicMock()
    brain.search = AsyncMock(return_value=[FakeEntry(i) for i in range(MIN_SIGNALS)])
    brain.write = AsyncMock(return_value=99)
    pool = MagicMock()
    pool.complete = AsyncMock(return_value="Cross-signal insight: UK tax space has multiple converging opportunities.")

    thinker = LateralThinker(pool=pool, brain=brain)
    result = await thinker.synthesise()

    assert result is not None
    pool.complete.assert_called_once()
    brain.write.assert_called_once()
    call_kwargs = brain.write.call_args.kwargs
    assert call_kwargs.get("category") == "lateral_thought"


async def test_lateral_thinker_returns_none_on_llm_failure():
    from clawbot.lateral_thinker import LateralThinker, MIN_SIGNALS

    fresh_ts = time.time() - 86400

    class FakeEntry:
        def __init__(self, i):
            self.content = f"signal {i}"
            self.metadata = {"ts": fresh_ts}

    brain = MagicMock()
    brain.search = AsyncMock(return_value=[FakeEntry(i) for i in range(MIN_SIGNALS)])
    brain.write = AsyncMock()
    pool = MagicMock()
    pool.complete = AsyncMock(side_effect=RuntimeError("rate limit"))

    thinker = LateralThinker(pool=pool, brain=brain)
    result = await thinker.synthesise()

    assert result is None
    brain.write.assert_not_called()
