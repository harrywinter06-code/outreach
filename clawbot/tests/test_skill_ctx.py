import pytest
from clawbot.skill_ctx import SkillMeta, SkillCallRecord

def test_skill_meta_minimal_fields():
    meta = SkillMeta(
        name="http_fetch",
        description="GET a URL, return sanitized text",
        params={"url": "str"},
        returns={"text": "str"},
    )
    assert meta.name == "http_fetch"
    assert meta.cost_estimate_usd == 0.0
    assert meta.requires_approval is False

def test_skill_meta_rejects_invalid_name():
    with pytest.raises(ValueError, match="must be lowercase snake_case"):
        SkillMeta(name="HttpFetch", description="x", params={}, returns={})

def test_skill_meta_rejects_reserved_name():
    with pytest.raises(ValueError, match="reserved"):
        SkillMeta(name="ctx", description="x", params={}, returns={})

def test_skill_call_record_immutable():
    rec = SkillCallRecord(
        skill_name="http_fetch", caller_id="ceo", params={"url": "x"},
        result={"text": "y"}, cost_usd=0.0, latency_ms=10, ok=True, error=None,
    )
    with pytest.raises(AttributeError):
        rec.ok = False  # type: ignore


import asyncio
from clawbot.skill_ctx import make_noop_ctx

def test_noop_ctx_exposes_all_surfaces():
    ctx = make_noop_ctx(caller_id="test", budget_usd=1.0)
    assert ctx.caller_id == "test"
    assert ctx.budget_usd == 1.0
    # Every documented surface must be present
    for surface in ("http", "sql", "llm", "vector", "secret", "fs", "time", "operator", "bus", "log"):
        assert hasattr(ctx, surface), f"missing surface: {surface}"

def test_noop_http_get_returns_empty():
    ctx = make_noop_ctx(caller_id="test", budget_usd=1.0)
    result = asyncio.run(ctx.http.get("https://example.com"))
    assert result == {"status": 200, "text": "", "headers": {}}
