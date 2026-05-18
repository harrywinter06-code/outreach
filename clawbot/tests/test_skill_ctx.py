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
    assert ctx.business_id is None, "business_id defaults to None for non-business cycles"
    # Every documented surface must be present
    for surface in ("http", "sql", "llm", "vector", "secret", "fs", "time", "operator", "bus", "log"):
        assert hasattr(ctx, surface), f"missing surface: {surface}"


def test_noop_ctx_accepts_business_id():
    """Z2.5 attribution: per-business-cycle ctx carries business_id for downstream
    skill_calls INSERT and Stripe payment-link metadata."""
    ctx = make_noop_ctx(caller_id="biz_runner", budget_usd=0.05, business_id="biz_abc123")
    assert ctx.business_id == "biz_abc123"

def test_noop_http_get_returns_empty():
    ctx = make_noop_ctx(caller_id="test", budget_usd=1.0)
    result = asyncio.run(ctx.http.get("https://example.com"))
    assert result == {"status": 200, "text": "", "headers": {}}


from unittest.mock import AsyncMock, MagicMock
from clawbot.skill_ctx import make_live_ctx

def test_live_ctx_passes_caller_id():
    pool = MagicMock()
    pool.complete = AsyncMock(return_value="hi")
    bus = MagicMock()
    bus.publish = AsyncMock(return_value="msg-id")
    brain = MagicMock()
    brain.recall = AsyncMock(return_value=[])
    brain.write = AsyncMock(return_value="vec-id")
    db_pool = MagicMock()
    escalation = MagicMock()
    escalation.notify = AsyncMock()
    secret_allowlist = ["FOO"]

    ctx = make_live_ctx(
        caller_id="worker-1", budget_usd=0.50,
        llm_pool=pool, bus=bus, brain=brain, db_pool=db_pool,
        escalation=escalation, secret_allowlist=secret_allowlist,
        workspace_root="/tmp/clawbot-workspace",
    )
    assert ctx.caller_id == "worker-1"
    assert ctx.budget_usd == 0.50

def test_live_ctx_passes_business_id_through():
    """Z2.5: make_live_ctx accepts business_id and the resulting ctx carries it."""
    ctx = make_live_ctx(
        caller_id="biz_runner", budget_usd=0.05,
        business_id="biz_council_42",
        llm_pool=MagicMock(), bus=MagicMock(), brain=MagicMock(),
        db_pool=MagicMock(), escalation=MagicMock(),
        secret_allowlist=["FOO"], workspace_root="/tmp/x",
    )
    assert ctx.business_id == "biz_council_42"
    assert ctx.caller_id == "biz_runner"


def test_live_ctx_business_id_defaults_to_none():
    """Executive cycles construct ctx without business_id — must stay NULL."""
    ctx = make_live_ctx(
        caller_id="ceo", budget_usd=0.10,
        llm_pool=MagicMock(), bus=MagicMock(), brain=MagicMock(),
        db_pool=MagicMock(), escalation=MagicMock(),
        secret_allowlist=["FOO"], workspace_root="/tmp/x",
    )
    assert ctx.business_id is None


def test_live_operator_message_publishes_to_bus_without_escalation_object():
    """_LiveOperator.message must NOT call escalation.notify (the router
    passes escalation=None into make_live_ctx, so the old `self._esc.notify`
    path crashed with AttributeError). Route via the bus-publish path that
    the EscalationStore subscriber consumes."""
    from clawbot.skill_ctx import _LiveOperator
    bus = MagicMock()
    bus.publish = AsyncMock(return_value="msg-id")
    op = _LiveOperator(escalation=None, bus=bus, caller_id="cmo")
    asyncio.run(op.message("first sale fired", level="info"))
    bus.publish.assert_called_once()
    topic, payload = bus.publish.call_args.args
    assert topic == "operator.escalation"
    assert payload["from_agent"] == "cmo"
    assert payload["summary"] == "first sale fired"
    assert payload["severity"] == "info"


def test_live_operator_message_coerces_unknown_level_to_info():
    from clawbot.skill_ctx import _LiveOperator
    bus = MagicMock()
    bus.publish = AsyncMock(return_value="msg-id")
    op = _LiveOperator(escalation=None, bus=bus, caller_id="cto")
    asyncio.run(op.message("hello", level="chatty"))
    payload = bus.publish.call_args.args[1]
    assert payload["severity"] == "info"


def test_live_secret_rejects_non_allowlisted():
    ctx = make_live_ctx(
        caller_id="w", budget_usd=0,
        llm_pool=MagicMock(), bus=MagicMock(), brain=MagicMock(),
        db_pool=MagicMock(), escalation=MagicMock(),
        secret_allowlist=["FOO"], workspace_root="/tmp/x",
    )
    import pytest
    with pytest.raises(PermissionError, match="not allowlisted"):
        ctx.secret.get("BAR")


# -- Task 19: ctx.browser tests -----------------------------------------------

from unittest.mock import patch


def test_noop_browser_returns_empty_success():
    ctx = make_noop_ctx(caller_id="t", budget_usd=1.0)
    result = asyncio.run(ctx.browser.run(task="open example.com"))
    assert result["success"] is True
    assert result["output"] == ""


def test_live_browser_dispatches_to_browser_worker():
    with patch("clawbot.browser_worker.run_browser_task", AsyncMock(return_value=MagicMock(
        success=True, output="page title: Example Domain", error="",
    ))) as mock_run:
        from clawbot.skill_ctx import _LiveBrowser
        pool = MagicMock()
        bc = _LiveBrowser(pool=pool, max_steps=15)
        result = asyncio.run(bc.run(task="get title of example.com"))
        mock_run.assert_called_once()
        assert "Example Domain" in result["output"]
        assert result["success"] is True


def test_live_browser_caps_concurrent_instances():
    from clawbot.skill_ctx import _LiveBrowser
    bc = _LiveBrowser(pool=MagicMock(), max_steps=15, max_concurrent=2)
    assert bc._sem._value == 2
