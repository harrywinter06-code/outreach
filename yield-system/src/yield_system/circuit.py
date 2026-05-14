"""§7 circuit breakers — hard stops that fire without review.

Every capital-touching or external-API call passes through `guard()`.
Each breaker raises CircuitTripped with the rule cited.
"""
import hashlib
from datetime import UTC, date, datetime, timedelta

from yield_system.config import settings
from yield_system.db import connect


class CircuitTripped(Exception):
    def __init__(self, rule: str, detail: str) -> None:
        super().__init__(f"[{rule}] {detail}")
        self.rule = rule
        self.detail = detail


def _today() -> date:
    return datetime.now(UTC).date()


def daily_burn_gbp(d: date | None = None) -> float:
    target = (d or _today()).isoformat()
    with connect() as c:
        row = c.execute(
            "SELECT COALESCE(SUM(cost_gbp), 0) AS s FROM ledger WHERE ts_iso LIKE ?",
            (f"{target}%",),
        ).fetchone()
    return float(row["s"])


def has_cre_on(d: date) -> bool:
    target = d.isoformat()
    with connect() as c:
        row = c.execute(
            "SELECT 1 FROM cre WHERE ts_iso LIKE ? LIMIT 1",
            (f"{target}%",),
        ).fetchone()
    return row is not None


def has_cre_since(d: date) -> bool:
    cutoff = datetime.combine(d, datetime.min.time(), tzinfo=UTC).isoformat()
    with connect() as c:
        row = c.execute(
            "SELECT 1 FROM cre WHERE ts_iso >= ? LIMIT 1",
            (cutoff,),
        ).fetchone()
    return row is not None


def total_spend_gbp() -> float:
    with connect() as c:
        row = c.execute("SELECT COALESCE(SUM(cost_gbp), 0) AS s FROM ledger").fetchone()
    return float(row["s"])


def experiment_spend_gbp(experiment: str) -> float:
    with connect() as c:
        row = c.execute(
            "SELECT COALESCE(SUM(cost_gbp), 0) AS s FROM ledger WHERE experiment = ?",
            (experiment,),
        ).fetchone()
    return float(row["s"])


def days_since_start() -> int:
    return (_today() - settings().project_start).days


def in_bootstrap() -> bool:
    return days_since_start() < settings().bootstrap_days


def _check_daily_burn() -> None:
    if in_bootstrap():
        return
    burn = daily_burn_gbp()
    limit = settings().daily_burn_limit_gbp
    if burn > limit and not has_cre_on(_today()):
        raise CircuitTripped(
            "§7.1",
            f"daily burn £{burn:.2f} exceeds £{limit:.2f} with no CRE today",
        )


def _check_drawdown() -> None:
    cap = settings().total_capital_gbp
    spent = total_spend_gbp()
    if spent / cap < settings().drawdown_pause_pct:
        return
    seven_days_ago = _today() - timedelta(days=7)
    if not has_cre_since(seven_days_ago):
        raise CircuitTripped(
            "§7.2",
            f"drawdown {spent / cap:.0%} (£{spent:.2f}/£{cap:.0f}) with no CRE in 7d",
        )


def _check_experiment_overrun(experiment: str, planned_cost: float) -> None:
    budget = settings().experiment_budgets_gbp.get(experiment)
    if budget is None:
        return
    spent = experiment_spend_gbp(experiment)
    if (spent + planned_cost) > budget * (1.0 + settings().overrun_terminate_pct):
        raise CircuitTripped(
            "§7.3",
            f"{experiment} would exceed budget £{budget:.0f} by >10% "
            f"(spent £{spent:.2f} + planned £{planned_cost:.2f})",
        )


def _check_loop(endpoint: str, params: dict[str, object], state_hash: str | None) -> None:
    if state_hash is None:
        return
    payload = f"{endpoint}|{sorted(params.items()) if params else ''}"
    h = hashlib.sha256(payload.encode()).hexdigest()[:16]
    threshold = settings().loop_repeat_threshold
    with connect() as c:
        row = c.execute(
            "SELECT count, last_state_hash FROM api_call_hashes WHERE hash = ?",
            (h,),
        ).fetchone()
        if row is None:
            c.execute(
                "INSERT INTO api_call_hashes(hash, ts_iso, count, last_state_hash) "
                "VALUES (?, ?, 1, ?)",
                (h, datetime.now(UTC).isoformat(), state_hash),
            )
            return
        prev_count = int(row["count"])
        prev_state = row["last_state_hash"]
        if state_hash is not None and prev_state != state_hash:
            c.execute(
                "UPDATE api_call_hashes SET count = 1, last_state_hash = ?, ts_iso = ? "
                "WHERE hash = ?",
                (state_hash, datetime.now(UTC).isoformat(), h),
            )
            return
        new_count = prev_count + 1
        c.execute(
            "UPDATE api_call_hashes SET count = ?, ts_iso = ? WHERE hash = ?",
            (new_count, datetime.now(UTC).isoformat(), h),
        )
        if new_count > threshold:
            raise CircuitTripped(
                "§7.4",
                f"call {endpoint} repeated {new_count}x with no state change",
            )


def guard(
    experiment: str,
    endpoint: str,
    planned_cost_gbp: float,
    params: dict[str, object] | None = None,
    state_hash: str | None = None,
) -> None:
    _check_daily_burn()
    _check_drawdown()
    _check_experiment_overrun(experiment, planned_cost_gbp)
    _check_loop(endpoint, params or {}, state_hash)


def terminal_gate() -> bool:
    """True if all experiments are at zero CRE AND remaining capital < £200."""
    remaining = settings().total_capital_gbp - total_spend_gbp()
    if remaining >= 200:
        return False
    with connect() as c:
        row = c.execute("SELECT COUNT(*) AS n FROM cre").fetchone()
    return int(row["n"]) == 0
