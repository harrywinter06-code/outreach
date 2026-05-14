"""§8 logging protocol — pre-action persistence, never deletes.

Every capital-touching or external-API action writes a PRE-entry to the
ledger (SQLite) and a JSONL append-only log line BEFORE execution.
After execution, an UPDATE writes actual_outcome + actual_cost.
"""
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from yield_system.config import settings
from yield_system.db import connect


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def _jsonl_path() -> Path:
    week = datetime.now(UTC).strftime("%G-W%V")
    return settings().log_dir / f"actions-{week}.jsonl"


def pre_log(experiment: str, action: str, expected_cost_gbp: float, expected_outcome: str) -> str:
    call_id = uuid.uuid4().hex
    ts = _now_iso()
    with connect() as c:
        c.execute(
            "INSERT INTO ledger(ts_iso, experiment, action, cost_gbp, expected, call_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (ts, experiment, action, expected_cost_gbp, expected_outcome, call_id),
        )
    _append_jsonl(
        {
            "ts": ts,
            "phase": "pre",
            "call_id": call_id,
            "experiment": experiment,
            "action": action,
            "cost_expected_gbp": expected_cost_gbp,
            "expected_outcome": expected_outcome,
        }
    )
    return call_id


def post_log(call_id: str, actual_outcome: str, actual_cost_gbp: float | None = None) -> None:
    ts = _now_iso()
    with connect() as c:
        if actual_cost_gbp is None:
            c.execute(
                "UPDATE ledger SET actual = ? WHERE call_id = ?",
                (actual_outcome, call_id),
            )
        else:
            c.execute(
                "UPDATE ledger SET actual = ?, cost_gbp = ? WHERE call_id = ?",
                (actual_outcome, actual_cost_gbp, call_id),
            )
    _append_jsonl(
        {
            "ts": ts,
            "phase": "post",
            "call_id": call_id,
            "actual_outcome": actual_outcome,
            "cost_actual_gbp": actual_cost_gbp,
        }
    )


def _append_jsonl(record: dict[str, Any]) -> None:
    p = _jsonl_path()
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, separators=(",", ":")) + "\n")


def record_cre(
    experiment: str,
    customer_id: str,
    amount_gbp: float,
    stripe_event_id: str,
    source: str = "stripe",
) -> bool:
    """Idempotent — returns True if new CRE recorded, False if duplicate."""
    ts = _now_iso()
    with connect() as c:
        cur = c.execute(
            "INSERT OR IGNORE INTO cre(ts_iso, experiment, customer_id, amount_gbp, "
            "stripe_event_id, source) VALUES (?, ?, ?, ?, ?, ?)",
            (ts, experiment, customer_id, amount_gbp, stripe_event_id, source),
        )
        is_new = cur.rowcount > 0
    if is_new:
        _append_jsonl(
            {
                "ts": ts,
                "phase": "cre",
                "experiment": experiment,
                "customer_id": customer_id,
                "amount_gbp": amount_gbp,
                "stripe_event_id": stripe_event_id,
            }
        )
    return is_new
