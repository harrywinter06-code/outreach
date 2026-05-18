"""Builtin compliance pack — pack-load + representative call tests."""
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


COMPLIANCE_SKILLS = {
    "sanctions_check", "kyc_verify_address", "fraud_score_transaction",
    "captcha_solve", "gdpr_data_export", "gdpr_delete_user",
    "tos_generate", "privacy_policy_generate",
    "dmca_takedown_request", "esign_send", "dispute_respond",
}


def test_compliance_pack_loads():
    reg = _registry()
    loaded = set(reg.list_names())
    missing = COMPLIANCE_SKILLS - loaded
    assert not missing, f"missing compliance skills: {missing}"


def test_gdpr_delete_user_requires_approval():
    reg = _registry()
    meta = reg.get_meta("gdpr_delete_user")
    assert meta is not None
    assert meta.requires_approval is True


def test_sanctions_check_no_match():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="compliance", budget_usd=0.0)
    ctx.http.get = AsyncMock(return_value={  # type: ignore[method-assign]
        "status": 200, "text": json.dumps({"matches": []}), "headers": {},
    })
    record = asyncio.run(reg.call("sanctions_check", {
        "name": "Some Common Name", "minimum_score": 85,
    }, ctx))
    assert record.ok is True
    assert record.result["is_match"] is False


def test_sanctions_check_match():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="compliance", budget_usd=0.0)
    ctx.http.get = AsyncMock(return_value={  # type: ignore[method-assign]
        "status": 200,
        "text": json.dumps({"matches": [{"name": "FLAGGED PERSON", "score": 95}]}),
        "headers": {},
    })
    record = asyncio.run(reg.call("sanctions_check", {
        "name": "Flagged Person",
    }, ctx))
    assert record.ok is True
    assert record.result["is_match"] is True
    assert len(record.result["matches"]) == 1


def test_fraud_score_finds_charge():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="compliance", budget_usd=0.0)
    ctx.payments.list_charges = AsyncMock(return_value=[  # type: ignore[method-assign]
        {"id": "ch_other", "outcome": {"risk_score": 5, "type": "authorized"}},
        {"id": "ch_target", "outcome": {"risk_score": 72, "type": "manual_review",
                                          "rule": {"description": "elevated risk"}}},
    ])
    record = asyncio.run(reg.call("fraud_score_transaction", {
        "charge_id": "ch_target",
    }, ctx))
    assert record.ok is True
    assert record.result["risk_score"] == 72
    assert record.result["outcome"] == "manual_review"


def test_fraud_score_not_found():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="compliance", budget_usd=0.0)
    ctx.payments.list_charges = AsyncMock(return_value=[])  # type: ignore[method-assign]
    record = asyncio.run(reg.call("fraud_score_transaction", {
        "charge_id": "ch_missing",
    }, ctx))
    assert record.ok is True
    assert record.result["risk_score"] == -1
    assert record.result["outcome"] == "not_found"


def test_tos_generate_uses_llm():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="compliance", budget_usd=0.05)
    ctx.llm.complete = AsyncMock(return_value="# Terms of Service\n\n...")  # type: ignore[method-assign]
    record = asyncio.run(reg.call("tos_generate", {
        "company_name": "Clawbot Ltd", "jurisdiction": "England & Wales",
        "product_description": "agent platform", "billing_model": "monthly",
    }, ctx))
    assert record.ok is True
    assert record.result["tos_markdown"].startswith("# Terms of Service")


def test_dispute_respond_routes_to_payments():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="compliance", budget_usd=0.0)
    ctx.payments.respond_to_dispute = AsyncMock(return_value={  # type: ignore[method-assign]
        "id": "dp_123", "status": "under_review", "evidence_submitted": True,
    })
    record = asyncio.run(reg.call("dispute_respond", {
        "dispute_id": "dp_123",
        "evidence": {"customer_communication": "see attached email log"},
    }, ctx))
    assert record.ok is True
    assert record.result["status"] == "under_review"
    assert record.result["submitted"] is True


def test_dmca_takedown_request_sends_email_with_template():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="compliance", budget_usd=0.0)
    ctx.email.send = AsyncMock(return_value={"id": "msg_dmca"})  # type: ignore[method-assign]
    record = asyncio.run(reg.call("dmca_takedown_request", {
        "to": "dmca@host.example",
        "infringing_url": "https://host.example/copy",
        "original_work_url": "https://us.example/original",
        "complainant_name": "C. O. Owner",
        "complainant_email": "owner@us.example",
        "complainant_address": "1 Street, City, UK",
    }, ctx))
    assert record.ok is True
    kwargs = ctx.email.send.call_args.kwargs
    assert "DMCA" in kwargs["subject"]
    assert "17 U.S.C. § 512(c)(3)" in kwargs["body_text"]
