"""Builtin writing skills — load + smoke-call the pure-stdlib one."""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

from clawbot.skill_registry import SkillRegistry
from clawbot.skill_ctx import make_noop_ctx

WRITE_DIR = Path(__file__).parent.parent / "agents" / "skills" / "_builtin" / "write"


def _registry() -> SkillRegistry:
    reg = SkillRegistry(skills_dir=WRITE_DIR)
    reg.discover()
    return reg


def test_write_pack_loads():
    reg = _registry()
    names = set(reg.list_names())
    expected = {
        "write_long_form_article", "write_tweet_thread", "write_linkedin_post",
        "write_cold_email", "write_landing_page_copy", "write_case_study",
        "summarize", "translate", "grammar_check", "readability_score",
        "tone_rewrite",
    }
    missing = expected - names
    assert not missing, f"missing write skills: {missing}"


def test_readability_score_pure_stdlib():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    record = asyncio.run(reg.call(
        "readability_score",
        {"text": "This is a simple sentence. Another short one follows here."},
        ctx,
    ))
    assert record.ok is True
    assert isinstance(record.result["grade_level"], float)
    assert isinstance(record.result["reading_ease"], float)


def test_summarize_parses_bulleted_output():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    ctx.llm.complete = AsyncMock(return_value=(
        "- First fact about the text.\n"
        "- Second fact.\n"
        "- Third fact."
    ))
    record = asyncio.run(reg.call(
        "summarize", {"text": "long text here", "max_bullets": 3}, ctx,
    ))
    assert record.ok is True
    assert record.result["count"] == 3
    assert len(record.result["bullets"]) == 3


def test_write_landing_page_copy_parses_json():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    ctx.llm.complete = AsyncMock(return_value=(
        '{"headline": "Ship faster",'
        ' "subhead": "Built for solo devs who hate yak-shaving.",'
        ' "bullets": ["Skip setup", "One command deploy", "No yaml"],'
        ' "cta": "Start building"}'
    ))
    record = asyncio.run(reg.call("write_landing_page_copy", {
        "product_name": "X", "value_prop": "Y", "audience": "Z",
    }, ctx))
    assert record.ok is True
    assert record.result["headline"] == "Ship faster"
    assert record.result["bullets"] == ["Skip setup", "One command deploy", "No yaml"]


def test_write_cold_email_falls_back_when_no_json():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    ctx.llm.complete = AsyncMock(return_value="Just a plain body, no JSON here.")
    record = asyncio.run(reg.call("write_cold_email", {
        "recipient_name": "Jane", "recipient_company": "Acme",
        "offer": "thing", "evidence": "",
    }, ctx))
    assert record.ok is True
    assert "Acme" in record.result["subject"]
    assert record.result["body_text"] == "Just a plain body, no JSON here."
