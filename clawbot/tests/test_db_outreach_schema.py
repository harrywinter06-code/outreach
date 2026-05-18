"""Confirm Database.init_schema declares the leads + suppression tables.

Source-level assertion only — real schema bringup needs asyncpg + a live
postgres which is unavailable locally (operating_facts.md). The CI/canary
on the VPS exercises the actual CREATE TABLE."""
from pathlib import Path


def test_init_schema_declares_leads_and_suppression():
    db_source = (
        Path(__file__).parent.parent / "src" / "clawbot" / "db.py"
    ).read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS leads" in db_source
    assert "CREATE TABLE IF NOT EXISTS suppression" in db_source
    assert "idx_leads_stage" in db_source
