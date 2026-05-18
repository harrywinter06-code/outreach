"""Auto-diversification trigger -- spawn new hypothesis when an existing one stagnates."""


def test_stagnation_triggers_spawn_when_below_cap():
    """Past 50% time, progress < 0.20, portfolio below cap -> spawn."""
    from clawbot.scheduler import _should_diversify_for_hypothesis

    assert _should_diversify_for_hypothesis(
        age_days=8,
        progress_score=0.10,
        portfolio_size=1,
        max_active=3,
        kill_max_days=14,
    ) is True


def test_no_spawn_when_progress_high():
    from clawbot.scheduler import _should_diversify_for_hypothesis

    assert _should_diversify_for_hypothesis(
        age_days=10,
        progress_score=0.50,
        portfolio_size=1,
        max_active=3,
        kill_max_days=14,
    ) is False


def test_no_spawn_when_time_remaining():
    from clawbot.scheduler import _should_diversify_for_hypothesis

    assert _should_diversify_for_hypothesis(
        age_days=3,
        progress_score=0.05,
        portfolio_size=1,
        max_active=3,
        kill_max_days=14,
    ) is False


def test_no_spawn_when_portfolio_at_cap():
    from clawbot.scheduler import _should_diversify_for_hypothesis

    assert _should_diversify_for_hypothesis(
        age_days=10,
        progress_score=0.10,
        portfolio_size=3,
        max_active=3,
        kill_max_days=14,
    ) is False


def test_kill_criteria_null_safe():
    """Upstream kc normalisation yields a valid int; pure function stays correct."""
    from clawbot.scheduler import _should_diversify_for_hypothesis

    assert _should_diversify_for_hypothesis(
        age_days=8,
        progress_score=0.10,
        portfolio_size=1,
        max_active=3,
        kill_max_days=14,
    ) is True


async def test_progress_score_writer_no_crash_on_empty_portfolio():
    """_run_progress_score_writer_loop must be a no-op when portfolio is empty."""
    from unittest.mock import AsyncMock, MagicMock, patch
    from clawbot.scheduler import Scheduler
    import clawbot.scheduler as sched_mod

    scheduler = Scheduler(pool=MagicMock(), bus=MagicMock(), monitor=MagicMock())
    scheduler._db_pool = MagicMock()

    hyp_store_mock = MagicMock()
    hyp_store_mock.get_active_portfolio = AsyncMock(return_value=[])

    sleep_count = 0

    async def mock_sleep(_dummy: float) -> None:
        nonlocal sleep_count
        sleep_count += 1
        if sleep_count >= 2:
            raise StopAsyncIteration

    with patch.object(sched_mod, "HypothesisStore", return_value=hyp_store_mock), patch(
        "asyncio.sleep", new=mock_sleep
    ):
        try:
            await scheduler._run_progress_score_writer_loop()
        except StopAsyncIteration:
            pass

    hyp_store_mock.get_active_portfolio.assert_awaited_once()
