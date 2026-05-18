"""Auto-diversification trigger — spawn new hypothesis when an existing one stagnates."""
def test_stagnation_triggers_spawn_when_below_cap():
    """Past 50% time, progress < 0.20, portfolio below cap → spawn."""
    from clawbot.scheduler import _should_diversify_for_hypothesis

    assert _should_diversify_for_hypothesis(
        age_days=8,           # 50%+ of 14-day kill window
        progress_score=0.10,
        portfolio_size=1,
        max_active=3,
        kill_max_days=14,
    ) is True


def test_no_spawn_when_progress_high():
    from clawbot.scheduler import _should_diversify_for_hypothesis
    assert _should_diversify_for_hypothesis(
        age_days=10, progress_score=0.50,  # past 50% time but good progress
        portfolio_size=1, max_active=3, kill_max_days=14,
    ) is False


def test_no_spawn_when_time_remaining():
    from clawbot.scheduler import _should_diversify_for_hypothesis
    assert _should_diversify_for_hypothesis(
        age_days=3, progress_score=0.05,  # bad progress but early
        portfolio_size=1, max_active=3, kill_max_days=14,
    ) is False


def test_no_spawn_when_portfolio_at_cap():
    from clawbot.scheduler import _should_diversify_for_hypothesis
    assert _should_diversify_for_hypothesis(
        age_days=10, progress_score=0.10,
        portfolio_size=3, max_active=3, kill_max_days=14,
    ) is False
