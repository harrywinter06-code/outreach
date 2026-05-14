from datetime import date
from pathlib import Path

import pytest

from yield_system.config import Settings, reset_settings_for_test
from yield_system.db import init_schema


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    data = tmp_path / "data"
    logs = tmp_path / "logs"
    data.mkdir()
    logs.mkdir()
    monkeypatch.delenv("YIELD_ENV", raising=False)
    s = Settings(
        env="dev",
        data_dir=data,
        log_dir=logs,
        project_start=date(2026, 5, 14),
        daily_burn_limit_gbp=6.0,
        total_capital_gbp=1000.0,
        bootstrap_days=7,
        experiment_budgets_gbp={
            "sanctions": 150.0,
            "postcode": 100.0,
            "webhookq": 120.0,
            "email": 80.0,
            "_test": 50.0,
        },
    )
    reset_settings_for_test(s)
    init_schema()
    return s
