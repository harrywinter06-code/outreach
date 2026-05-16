import pytest
from clawbot.scheduler import _clamp_wakeup


def test_clamp_wakeup_respects_floor():
    assert _clamp_wakeup(10) == 60


def test_clamp_wakeup_respects_ceiling():
    assert _clamp_wakeup(9999) == 1800


def test_clamp_wakeup_passes_valid_value():
    assert _clamp_wakeup(300) == 300


def test_clamp_wakeup_at_budget_threshold():
    assert _clamp_wakeup(60, budget_fraction=0.70) == 1800


def test_clamp_wakeup_above_budget_threshold():
    assert _clamp_wakeup(300, budget_fraction=0.85) == 1800


def test_clamp_wakeup_below_budget_threshold():
    assert _clamp_wakeup(300, budget_fraction=0.69) == 300


def test_clamp_wakeup_zero_budget():
    assert _clamp_wakeup(600, budget_fraction=0.0) == 600


def test_clamp_wakeup_float_input():
    assert _clamp_wakeup(300.7) == 300
