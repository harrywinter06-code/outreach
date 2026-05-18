"""Builtin finance + UK-gov pack — pack-load + representative call tests."""
import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

from clawbot.skill_registry import SkillRegistry
from clawbot.skill_ctx import make_noop_ctx

BUILTIN_DIR = Path(__file__).parent.parent / "agents" / "skills" / "_builtin"


def _registry() -> SkillRegistry:
    reg = SkillRegistry(skills_dir=BUILTIN_DIR)
    reg.discover()
    return reg


FINANCE_SKILLS = {
    "companies_house_search", "companies_house_get_company",
    "companies_house_get_officers", "companies_house_get_filings",
    "companies_house_monitor_filings", "hmrc_check_vat_number",
    "freeagent_create_invoice", "freeagent_record_expense",
    "xero_reconcile_transaction",
    "compute_runway_months", "ir35_determine_status",
}


def test_finance_pack_loads():
    reg = _registry()
    loaded = set(reg.list_names())
    missing = FINANCE_SKILLS - loaded
    assert not missing, f"missing finance skills: {missing}"


def test_companies_house_search_parses_response():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="cfo", budget_usd=0.0)
    ctx.http.get = AsyncMock(return_value={  # type: ignore[method-assign]
        "status": 200,
        "text": json.dumps({
            "items": [{"company_number": "12345678", "title": "ACME LTD"}],
            "total_results": 1,
        }),
        "headers": {},
    })
    record = asyncio.run(reg.call("companies_house_search", {
        "query": "acme", "items_per_page": 20,
    }, ctx))
    assert record.ok is True
    assert record.result["total_results"] == 1
    assert record.result["items"][0]["company_number"] == "12345678"


def test_compute_runway_months_no_ledger_returns_infinity_sentinel():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="cfo", budget_usd=0.0)
    # Default _NoopSql returns []
    record = asyncio.run(reg.call("compute_runway_months", {
        "cash_gbp": 50000.0,
    }, ctx))
    assert record.ok is True
    assert record.result["months"] == 999.0
    assert record.result["burn_30d_gbp"] == 0.0


def test_compute_runway_months_with_burn():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="cfo", budget_usd=0.0)
    ctx.sql.query = AsyncMock(return_value=[{"spent": 2500.0}])  # type: ignore[method-assign]
    record = asyncio.run(reg.call("compute_runway_months", {
        "cash_gbp": 30000.0,
    }, ctx))
    assert record.ok is True
    assert record.result["months"] == 12.0
    assert record.result["burn_30d_gbp"] == 2500.0


def test_ir35_outside_substitution_dominant():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="cfo", budget_usd=0.0)
    record = asyncio.run(reg.call("ir35_determine_status", {
        "has_unfettered_substitution": True,
        "client_controls_how_work_done": False,
        "mutuality_of_obligation": False,
    }, ctx))
    assert record.ok is True
    assert record.result["status"] == "outside_ir35"


def test_ir35_inside_when_controlled_and_moo():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="cfo", budget_usd=0.0)
    record = asyncio.run(reg.call("ir35_determine_status", {
        "has_unfettered_substitution": False,
        "client_controls_how_work_done": True,
        "mutuality_of_obligation": True,
        "part_and_parcel_of_organisation": True,
    }, ctx))
    assert record.ok is True
    assert record.result["status"] == "inside_ir35"


def test_ir35_undetermined_when_mixed():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="cfo", budget_usd=0.0)
    record = asyncio.run(reg.call("ir35_determine_status", {
        "has_unfettered_substitution": False,
        "client_controls_how_work_done": True,
        "mutuality_of_obligation": False,
        "financial_risk": True,
    }, ctx))
    assert record.ok is True
    # +0.2 personal -0.2 no-MOO +0.3 control -0.15 risk = +0.15 → undetermined
    assert record.result["status"] == "undetermined"
