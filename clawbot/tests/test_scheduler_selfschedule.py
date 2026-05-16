import asyncio
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from clawbot.scheduler import _clamp_wakeup, _parse_product_reply, _extract_gumroad_product_id


def test_clamp_wakeup_respects_floor():
    assert _clamp_wakeup(10) == 60


def test_clamp_wakeup_respects_ceiling():
    assert _clamp_wakeup(9999) == 1800


def test_clamp_wakeup_passes_valid_value():
    assert _clamp_wakeup(300) == 300


def test_clamp_wakeup_at_budget_threshold():
    assert _clamp_wakeup(60, budget_fraction=0.70) == 1800


def test_clamp_wakeup_above_budget_threshold():
    assert _clamp_wakeup(300, budget_fraction=0.85) == 1800


def test_clamp_wakeup_below_budget_threshold():
    assert _clamp_wakeup(300, budget_fraction=0.69) == 300


def test_clamp_wakeup_zero_budget():
    assert _clamp_wakeup(600, budget_fraction=0.0) == 600


def test_clamp_wakeup_float_input():
    assert _clamp_wakeup(300.7) == 300


def test_parse_product_reply_extracts_url_and_chain():
    url, chain_id = _parse_product_reply(
        "PRODUCT_URL:https://gumroad.com/l/uk-isa-guide CHAIN:abc123-456"
    )
    assert url == "https://gumroad.com/l/uk-isa-guide"
    assert chain_id == "abc123-456"


def test_parse_product_reply_returns_none_for_missing_url():
    assert _parse_product_reply("no url here") == (None, None)


def test_parse_product_reply_handles_extra_whitespace():
    url, chain_id = _parse_product_reply(
        "  PRODUCT_URL: https://gumroad.com/l/test   CHAIN: chain-xyz  "
    )
    assert url == "https://gumroad.com/l/test"
    assert chain_id == "chain-xyz"


def test_extract_gumroad_product_id_standard_url():
    assert _extract_gumroad_product_id("https://gumroad.com/l/uk-isa-guide") == "uk-isa-guide"


def test_extract_gumroad_product_id_subdomain_url():
    assert _extract_gumroad_product_id("https://seller.gumroad.com/l/abc123") == "abc123"


def test_extract_gumroad_product_id_invalid():
    assert _extract_gumroad_product_id("https://example.com/product") is None


async def test_directive_bus_message_includes_chain_id():
    """Every directive published to *.directive must carry a chain_id UUID."""
    from clawbot.scheduler import Scheduler

    log = []

    pool = MagicMock()
    pool.complete = AsyncMock(
        return_value='{"action": "wait", "directive": "nothing", "priority": "low"}'
    )
    bus = MagicMock()
    bus.publish = AsyncMock(
        side_effect=lambda topic, payload: log.append((topic, payload))
    )
    monitor = MagicMock()
    monitor.should_halt = AsyncMock(return_value=False)
    monitor.spend_limit_reached = AsyncMock(return_value=False)

    s = Scheduler(pool=pool, bus=bus, monitor=monitor)

    agents_dir = MagicMock()
    soul_file = MagicMock()
    soul_file.exists.return_value = True
    soul_file.read_text.return_value = "# SOUL"
    agents_dir.__truediv__ = lambda self, x: MagicMock(
        __truediv__=lambda self2, y: soul_file
    )
    s._agents_dir = agents_dir
    s._metrics_dir = MagicMock()
    s._metrics_dir.__truediv__ = lambda self, x: MagicMock(exists=lambda: False)

    with patch("clawbot.fitness_writer.append_observation"):
        with patch.object(s, "_load_metrics", AsyncMock(return_value={"revenue_7d_gbp": 0.0})):
            with patch.object(s, "_brain_recall", AsyncMock(return_value="")):
                with patch.object(s, "_brain_remember", AsyncMock()):
                    with patch.object(s, "_write_company_metrics", AsyncMock()):
                        with patch.object(s, "_record_variant_observation", AsyncMock()):
                            await s._run_executive_cycle()

    directive_publishes = [(t, p) for t, p in log if t == "ceo.directive"]
    assert len(directive_publishes) == 1
    payload = directive_publishes[0][1]
    assert "chain_id" in payload
    uuid.UUID(payload["chain_id"])  # validates it's a real UUID


async def test_worker_prompt_includes_inbox_messages():
    """Messages published to inbox.{agent_id} must appear in the worker's prompt."""
    from clawbot.scheduler import Scheduler
    from clawbot.agent_registry import AgentSpec

    prompts_seen = []

    pool = MagicMock()

    async def capture_prompt(messages, tier="worker"):
        prompts_seen.append(messages)
        return '{"action": "wait"}'

    pool.complete = capture_prompt

    bus = MagicMock()
    bus.publish = AsyncMock()
    bus.read_and_ack = AsyncMock(
        return_value=[{"from": "ceo", "message": "prioritise the ISA guide", "chain_id": "abc"}]
    )

    s = Scheduler(pool=pool, bus=bus, monitor=MagicMock())
    s._next_wakeup_s = {}

    spec = AgentSpec(
        agent_id="worker-001",
        role="Researcher",
        supervisor="ceo",
        soul_path="agents/worker-001/SOUL.md",
        status="active",
        created_at="2026-01-01T00:00:00Z",
        call_interval_s=600,
    )
    soul_mock = MagicMock()
    soul_mock.exists.return_value = True
    soul_mock.read_text.return_value = "# SOUL"

    with patch.object(s, "_resolve_soul_path", return_value=soul_mock):
        try:
            await asyncio.wait_for(s._worker_agent_loop(spec), timeout=0.5)
        except asyncio.TimeoutError:
            pass

    assert len(prompts_seen) >= 1
    user_msg = prompts_seen[0][1]["content"]
    assert "prioritise the ISA guide" in user_msg


async def test_worker_prompt_includes_pending_tasks():
    """Pending tasks from TaskStore must appear in the worker's prompt."""
    from clawbot.scheduler import Scheduler
    from clawbot.agent_registry import AgentSpec

    prompts_seen = []

    pool = MagicMock()

    async def capture_prompt(messages, tier="worker"):
        prompts_seen.append(messages)
        return '{"action": "wait"}'

    pool.complete = capture_prompt

    bus = MagicMock()
    bus.publish = AsyncMock()
    bus.read_and_ack = AsyncMock(return_value=[])

    task_store = MagicMock()
    task_store.read_tasks = MagicMock(
        return_value=[{
            "task_id": "aaaabbbb-cccc-dddd-eeee-ffffgggghhh",
            "title": "Write UK ISA guide",
            "description": "Comprehensive guide to ISA rules",
            "chain_id": "abc",
            "status": "pending",
        }]
    )

    s = Scheduler(pool=pool, bus=bus, monitor=MagicMock(), task_store=task_store)
    s._next_wakeup_s = {}

    spec = AgentSpec(
        agent_id="worker-001",
        role="Researcher",
        supervisor="ceo",
        soul_path="agents/worker-001/SOUL.md",
        status="active",
        created_at="2026-01-01T00:00:00Z",
        call_interval_s=600,
    )
    soul_mock = MagicMock()
    soul_mock.exists.return_value = True
    soul_mock.read_text.return_value = "# SOUL"

    with patch.object(s, "_resolve_soul_path", return_value=soul_mock):
        try:
            await asyncio.wait_for(s._worker_agent_loop(spec), timeout=0.5)
        except asyncio.TimeoutError:
            pass

    assert len(prompts_seen) >= 1
    user_msg = prompts_seen[0][1]["content"]
    assert "Write UK ISA guide" in user_msg
