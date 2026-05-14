from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    env: Literal["dev", "prod"] = "dev"

    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_sanctions: str = ""
    stripe_price_postcode: str = ""
    stripe_price_webhookq: str = ""
    stripe_price_email: str = ""

    daily_burn_limit_gbp: float = 6.0
    total_capital_gbp: float = 1000.0
    bootstrap_days: int = 7
    project_start: date = date(2026, 5, 14)

    experiment_budgets_gbp: dict[str, float] = Field(
        default_factory=lambda: {
            "sanctions": 150.0,
            "postcode": 100.0,
            "webhookq": 120.0,
            "email": 80.0,
        }
    )

    drawdown_pause_pct: float = 0.20
    overrun_terminate_pct: float = 0.10
    loop_repeat_threshold: int = 3

    data_dir: Path = Path("./data")
    log_dir: Path = Path("./logs")


_settings: Settings | None = None


def settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
        _settings.data_dir.mkdir(parents=True, exist_ok=True)
        _settings.log_dir.mkdir(parents=True, exist_ok=True)
    return _settings


def reset_settings_for_test(s: Settings) -> None:
    global _settings
    _settings = s
