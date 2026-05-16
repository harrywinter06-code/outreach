"""
Metrics store — the single source of truth that shareholders read directly.
All writes go through this module. Shareholders read the JSON files on disk.
No agent may write metrics files except through this module.
"""
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, UTC
from pathlib import Path
import redis.asyncio as aioredis

METRICS_DIR = Path("/metrics")


@dataclass
class RevenueMetrics:
    total_lifetime: float = 0.0
    today: float = 0.0
    this_week: float = 0.0
    last_week: float = 0.0
    growth_pct_week_on_week: float = 0.0
    trend_direction: str = "flat"  # "up", "down", "flat"
    revenue_flat_days: int = 0
    by_source: dict[str, float] = field(default_factory=dict)
    updated_at: str = ""


@dataclass
class StrategyLog:
    current_strategy: str = "undefined"
    days_active: int = 0
    strategy_unchanged_days: int = 0
    pivot_count_this_month: int = 0
    experiments_launched_this_week: int = 0
    last_changed: str = ""
    history: list[dict] = field(default_factory=list)


@dataclass
class ComputeAllocation:
    by_strategy: dict[str, float] = field(default_factory=dict)  # strategy: pct
    exploration_pct: float = 20.0
    updated_at: str = ""


@dataclass
class CompoundingAssets:
    email_subscribers: int = 0
    content_pieces_published: int = 0
    returning_customers: int = 0
    social_following: int = 0
    domain_authority: float = 0.0
    week_on_week_changes: dict[str, int] = field(default_factory=dict)
    updated_at: str = ""


@dataclass
class Opportunity:
    title: str
    description: str
    source: str
    confidence: float  # 0.0 – 1.0
    time_window_days: int
    estimated_value: str
    discovered_at: str = ""

    def __post_init__(self):
        self.discovered_at = self.discovered_at or datetime.now(UTC).isoformat()


@dataclass
class OpportunityFeed:
    opportunities: list[Opportunity] = field(default_factory=list)
    last_scan: str = ""


@dataclass
class DashboardWidget:
    id: str
    type: str          # "text" | "metric" | "list"
    title: str
    agent: str
    updated_at: str = ""
    content: str = ""
    value: float = 0.0
    unit: str = ""
    max_value: float = 0.0
    items: list[str] = field(default_factory=list)

    def __post_init__(self):
        self.updated_at = self.updated_at or datetime.now(UTC).isoformat()


class MetricsStore:
    """Write and read all metrics. Shareholders read the JSON files directly."""

    def __init__(self, metrics_dir: Path = METRICS_DIR, redis_url: str | None = None):
        self._dir = metrics_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._redis_url = redis_url
        self._redis: aioredis.Redis | None = None

    async def connect(self):
        if self._redis_url:
            self._redis = await aioredis.from_url(self._redis_url, decode_responses=True)

    def _write(self, filename: str, data: dict) -> None:
        path = self._dir / filename
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _read(self, filename: str, default: dict) -> dict:
        path = self._dir / filename
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    # Revenue

    async def record_revenue(self, amount: float, source: str) -> RevenueMetrics:
        current = RevenueMetrics(**self._read("revenue.json", asdict(RevenueMetrics())))
        current.total_lifetime += amount
        current.today += amount
        current.this_week += amount
        current.by_source[source] = current.by_source.get(source, 0.0) + amount

        if current.last_week > 0:
            current.growth_pct_week_on_week = (
                (current.this_week - current.last_week) / current.last_week
            ) * 100
        if current.this_week > current.last_week:
            current.trend_direction = "up"
            current.revenue_flat_days = 0
        elif current.this_week < current.last_week:
            current.trend_direction = "down"
        current.updated_at = datetime.now(UTC).isoformat()

        self._write("revenue.json", asdict(current))
        self._write(
            "revenue_by_source.json",
            {k: round(v / max(current.total_lifetime, 0.01) * 100, 1) for k, v in current.by_source.items()},
        )
        if self._redis:
            await self._redis.publish("clawbot:metrics:revenue", json.dumps({"amount": amount, "source": source}))
        return current

    async def increment_flat_days(self) -> int:
        current = RevenueMetrics(**self._read("revenue.json", asdict(RevenueMetrics())))
        if current.today == 0:
            current.revenue_flat_days += 1
        current.updated_at = datetime.now(UTC).isoformat()
        self._write("revenue.json", asdict(current))
        return current.revenue_flat_days

    # Strategy

    def update_strategy(self, strategy_name: str) -> StrategyLog:
        current = StrategyLog(**self._read("strategy_log.json", asdict(StrategyLog())))
        if current.current_strategy != strategy_name:
            if current.current_strategy != "undefined":
                current.history.append({
                    "strategy": current.current_strategy,
                    "days_active": current.days_active,
                    "ended_at": datetime.now(UTC).isoformat(),
                })
            current.current_strategy = strategy_name
            current.days_active = 0
            current.strategy_unchanged_days = 0
            current.pivot_count_this_month += 1
            current.last_changed = datetime.now(UTC).isoformat()
        else:
            current.days_active += 1
            current.strategy_unchanged_days += 1
        self._write("strategy_log.json", asdict(current))
        return current

    def record_experiment_launched(self) -> None:
        current = StrategyLog(**self._read("strategy_log.json", asdict(StrategyLog())))
        current.experiments_launched_this_week += 1
        self._write("strategy_log.json", asdict(current))

    # Compute allocation

    def update_compute_allocation(self, by_strategy: dict[str, float], exploration_pct: float) -> None:
        allocation = ComputeAllocation(
            by_strategy=by_strategy,
            exploration_pct=exploration_pct,
            updated_at=datetime.now(UTC).isoformat(),
        )
        self._write("compute_allocation.json", asdict(allocation))

    # Compounding assets

    def update_compounding_assets(self, **kwargs: int | float) -> CompoundingAssets:
        current_dict = self._read("compounding_assets.json", asdict(CompoundingAssets()))
        changes = {}
        for k, v in kwargs.items():
            if k in current_dict:
                changes[k] = int(v) - int(current_dict.get(k, 0))
                current_dict[k] = v
        current_dict["week_on_week_changes"] = changes
        current_dict["updated_at"] = datetime.now(UTC).isoformat()
        self._write("compounding_assets.json", current_dict)
        return CompoundingAssets(**current_dict)

    # Opportunities

    def add_opportunity(self, opp: Opportunity) -> None:
        current = self._read("opportunity_feed.json", asdict(OpportunityFeed()))
        opps = current.get("opportunities", [])
        opps.append(asdict(opp))
        # Keep only the 20 most recent high-confidence opportunities
        opps = sorted(opps, key=lambda x: x["confidence"], reverse=True)[:20]
        self._write("opportunity_feed.json", {
            "opportunities": opps,
            "last_scan": datetime.now(UTC).isoformat(),
        })

    def get_top_opportunities(self, min_confidence: float = 0.5) -> list[Opportunity]:
        current = self._read("opportunity_feed.json", asdict(OpportunityFeed()))
        return [
            Opportunity(**o) for o in current.get("opportunities", [])
            if o["confidence"] >= min_confidence
        ]

    # Dashboard widgets (agent-writable)

    def upsert_widget(self, widget: DashboardWidget) -> None:
        widget.updated_at = datetime.now(UTC).isoformat()
        current = self._read("dashboard_widgets.json", {"widgets": []})
        widgets = current.get("widgets", [])
        widgets = [w for w in widgets if w.get("id") != widget.id]
        widgets.append(asdict(widget))
        self._write("dashboard_widgets.json", {"widgets": widgets})

    def get_widgets(self) -> list[DashboardWidget]:
        current = self._read("dashboard_widgets.json", {"widgets": []})
        return [DashboardWidget(**w) for w in current.get("widgets", [])]

    def remove_widget(self, widget_id: str) -> None:
        current = self._read("dashboard_widgets.json", {"widgets": []})
        widgets = [w for w in current.get("widgets", []) if w.get("id") != widget_id]
        self._write("dashboard_widgets.json", {"widgets": widgets})
