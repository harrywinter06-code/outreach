"""Daily sanctions refresh — OFAC SDN + UK HMT OFSI.

Run via cron or manually: python scripts/refresh_sanctions.py
Passes through circuit.guard so a tripped breaker halts the refresh.
"""
import sys

from yield_system.circuit import CircuitTripped, guard
from yield_system.db import connect
from yield_system.experiments.sanctions import fire_webhooks_for_new_entries
from yield_system.ingest.sanctions_hmt import ingest as ingest_hmt
from yield_system.ingest.sanctions_ofac import ingest as ingest_ofac


def _names_added_since(n: int) -> list[str]:
    with connect() as c:
        rows = c.execute(
            "SELECT name_normalized FROM sanctions_entries ORDER BY id DESC LIMIT ?",
            (n,),
        ).fetchall()
    return [r["name_normalized"] for r in rows]


def _entry_count() -> int:
    with connect() as c:
        return int(c.execute("SELECT COUNT(*) AS n FROM sanctions_entries").fetchone()["n"])


def main() -> int:
    try:
        guard("sanctions", "ingest", planned_cost_gbp=0.0)
    except CircuitTripped as e:
        print(f"breaker tripped, aborting refresh: {e}", file=sys.stderr)
        return 2

    before = _entry_count()

    new_ofac = ingest_ofac()
    new_hmt = ingest_hmt()
    new_total = new_ofac + new_hmt

    new_names = _names_added_since(new_total) if new_total else []
    fired = fire_webhooks_for_new_entries(new_names)

    after = _entry_count()
    print(
        f"before={before} after={after} "
        f"ofac_new={new_ofac} hmt_new={new_hmt} webhooks_fired={fired}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
