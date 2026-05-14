import json
from pathlib import Path

import pytest

from yield_system.db import connect
from yield_system.log import post_log, pre_log, record_cre


def _read_jsonl(log_dir: Path) -> list[dict]:
    lines: list[dict] = []
    for f in sorted(log_dir.glob("actions-*.jsonl")):
        for line in f.read_text().splitlines():
            lines.append(json.loads(line))
    return lines


def test_pre_log_persists_to_ledger_and_jsonl(isolated_settings):
    call_id = pre_log("postcode", "GET /v1/postcode/SW1A1AA", 0.0001, "200_ok_lookup")
    assert call_id

    with connect() as c:
        row = c.execute("SELECT * FROM ledger WHERE call_id = ?", (call_id,)).fetchone()
    assert row["experiment"] == "postcode"
    assert row["action"] == "GET /v1/postcode/SW1A1AA"
    assert row["cost_gbp"] == pytest.approx(0.0001)
    assert row["expected"] == "200_ok_lookup"
    assert row["actual"] is None

    entries = _read_jsonl(isolated_settings.log_dir)
    assert len(entries) == 1
    assert entries[0]["phase"] == "pre"
    assert entries[0]["call_id"] == call_id


def test_post_log_updates_actual_and_appends_jsonl(isolated_settings):
    call_id = pre_log("sanctions", "ingest_ofac", 0.0, "fresh_list_pulled")
    post_log(call_id, "200_ok_2400_entries", actual_cost_gbp=0.0)

    with connect() as c:
        row = c.execute("SELECT actual FROM ledger WHERE call_id = ?", (call_id,)).fetchone()
    assert row["actual"] == "200_ok_2400_entries"

    entries = _read_jsonl(isolated_settings.log_dir)
    assert [e["phase"] for e in entries] == ["pre", "post"]


def test_call_id_unique_across_concurrent_pre_logs(isolated_settings):
    ids = {pre_log("postcode", "x", 0.0, "ok") for _ in range(50)}
    assert len(ids) == 50


def test_record_cre_idempotent_on_stripe_event_id(isolated_settings):
    new1 = record_cre("postcode", "cust_1", 15.0, "evt_abc")
    new2 = record_cre("postcode", "cust_1", 15.0, "evt_abc")
    assert new1 is True
    assert new2 is False

    with connect() as c:
        n = c.execute("SELECT COUNT(*) AS n FROM cre").fetchone()["n"]
    assert n == 1


def test_post_log_overrides_cost_when_actual_differs(isolated_settings):
    call_id = pre_log("sanctions", "openai_call", 0.001, "ok")
    post_log(call_id, "ok", actual_cost_gbp=0.005)

    with connect() as c:
        row = c.execute("SELECT cost_gbp FROM ledger WHERE call_id = ?", (call_id,)).fetchone()
    assert row["cost_gbp"] == pytest.approx(0.005)
