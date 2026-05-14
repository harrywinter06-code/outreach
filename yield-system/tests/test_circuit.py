from datetime import UTC, datetime, timedelta

import pytest
from freezegun import freeze_time

from yield_system.circuit import (
    CircuitTripped,
    daily_burn_gbp,
    guard,
    has_cre_on,
    in_bootstrap,
    terminal_gate,
    total_spend_gbp,
)
from yield_system.config import Settings, reset_settings_for_test
from yield_system.db import init_schema
from yield_system.log import post_log, pre_log, record_cre


def _set_start(tmp_path, days_ago: int) -> Settings:
    today = datetime.now(UTC).date()
    s = Settings(
        env="dev",
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        project_start=today - timedelta(days=days_ago),
        bootstrap_days=7,
        daily_burn_limit_gbp=6.0,
        total_capital_gbp=1000.0,
        experiment_budgets_gbp={"postcode": 100.0, "sanctions": 150.0, "_test": 50.0},
    )
    s.data_dir.mkdir(parents=True, exist_ok=True)
    s.log_dir.mkdir(parents=True, exist_ok=True)
    reset_settings_for_test(s)
    init_schema()
    return s


def test_bootstrap_window_suspends_daily_burn_breaker(tmp_path):
    _set_start(tmp_path, days_ago=3)
    assert in_bootstrap()
    cid = pre_log("postcode", "expensive_call", 50.0, "ok")
    post_log(cid, "ok")
    guard("postcode", "next_call", 0.001)


def test_daily_burn_breaker_fires_post_bootstrap_without_cre(tmp_path):
    _set_start(tmp_path, days_ago=10)
    cid = pre_log("postcode", "expensive_call", 7.0, "ok")
    post_log(cid, "ok")
    with pytest.raises(CircuitTripped) as exc:
        guard("postcode", "next_call", 0.001)
    assert exc.value.rule == "§7.1"


def test_daily_burn_breaker_suppressed_when_cre_exists_today(tmp_path):
    _set_start(tmp_path, days_ago=10)
    cid = pre_log("postcode", "expensive_call", 7.0, "ok")
    post_log(cid, "ok")
    record_cre("postcode", "cust_x", 5.0, "evt_today")
    guard("postcode", "next_call", 0.001)


def test_drawdown_breaker_fires_at_20pct_with_no_recent_cre(tmp_path):
    _set_start(tmp_path, days_ago=10)
    cid = pre_log("postcode", "burn", 250.0, "ok")
    post_log(cid, "ok")
    record_cre("postcode", "old", 5.0, "evt_old")
    with freeze_time(datetime.now(UTC) + timedelta(days=8)):
        with pytest.raises(CircuitTripped) as exc:
            guard("postcode", "next_call", 0.001)
        assert exc.value.rule == "§7.2"


def test_experiment_overrun_breaker_fires_above_110pct(tmp_path):
    _set_start(tmp_path, days_ago=10)
    cid = pre_log("_test", "burn", 50.0, "ok")
    post_log(cid, "ok")
    record_cre("_test", "x", 5.0, "evt_today2")
    with pytest.raises(CircuitTripped) as exc:
        guard("_test", "next_call", 6.0)
    assert exc.value.rule == "§7.3"


def test_loop_breaker_fires_after_threshold_with_no_state_change(tmp_path):
    _set_start(tmp_path, days_ago=10)
    record_cre("postcode", "x", 5.0, "evt_today3")
    params = {"q": "test"}
    for _ in range(3):
        guard("postcode", "/scrape", 0.0, params, state_hash="A")
    with pytest.raises(CircuitTripped) as exc:
        guard("postcode", "/scrape", 0.0, params, state_hash="A")
    assert exc.value.rule == "§7.4"


def test_loop_breaker_resets_on_state_change(tmp_path):
    _set_start(tmp_path, days_ago=10)
    record_cre("postcode", "x", 5.0, "evt_today4")
    params = {"q": "test"}
    for _ in range(3):
        guard("postcode", "/scrape", 0.0, params, state_hash="A")
    guard("postcode", "/scrape", 0.0, params, state_hash="B")
    guard("postcode", "/scrape", 0.0, params, state_hash="B")


def test_daily_burn_aggregates_correctly(tmp_path):
    _set_start(tmp_path, days_ago=3)
    cid1 = pre_log("postcode", "a", 0.25, "ok")
    post_log(cid1, "ok")
    cid2 = pre_log("sanctions", "b", 0.50, "ok")
    post_log(cid2, "ok")
    assert daily_burn_gbp() == pytest.approx(0.75)


def test_terminal_gate_true_when_no_cre_and_capital_below_floor(tmp_path):
    _set_start(tmp_path, days_ago=25)
    cid = pre_log("postcode", "burn", 850.0, "ok")
    post_log(cid, "ok")
    assert terminal_gate() is True


def test_terminal_gate_false_with_any_cre(tmp_path):
    _set_start(tmp_path, days_ago=25)
    cid = pre_log("postcode", "burn", 850.0, "ok")
    post_log(cid, "ok")
    record_cre("postcode", "x", 5.0, "evt_z")
    assert terminal_gate() is False


def test_has_cre_on_only_matches_target_date(tmp_path):
    _set_start(tmp_path, days_ago=10)
    record_cre("postcode", "x", 5.0, "evt_a")
    today = datetime.now(UTC).date()
    yesterday = today - timedelta(days=1)
    assert has_cre_on(today) is True
    assert has_cre_on(yesterday) is False


def test_total_spend_sums_across_experiments(tmp_path):
    _set_start(tmp_path, days_ago=3)
    for amt, exp in [(0.10, "postcode"), (0.20, "sanctions"), (0.30, "_test")]:
        cid = pre_log(exp, "x", amt, "ok")
        post_log(cid, "ok")
    assert total_spend_gbp() == pytest.approx(0.60)
