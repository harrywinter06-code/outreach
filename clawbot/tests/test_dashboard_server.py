"""Tests for EventBroadcaster and compute_links in dashboard.server."""
import asyncio
import pytest
from clawbot.dashboard.server import (
    EventBroadcaster, compute_links, _parse_directive_target,
    _build_flow_matrix, _build_spend_payload, _build_provider_health,
)


class TestEventBroadcaster:
    @pytest.mark.asyncio
    async def test_subscribe_returns_queue(self):
        bc = EventBroadcaster()
        q = bc.subscribe()
        assert q is not None

    @pytest.mark.asyncio
    async def test_broadcast_delivers_to_subscriber(self):
        bc = EventBroadcaster()
        q = bc.subscribe()
        await bc.broadcast({"type": "test", "value": 42})
        msg = q.get_nowait()
        assert '"type": "test"' in msg
        assert '"value": 42' in msg

    @pytest.mark.asyncio
    async def test_broadcast_to_multiple_subscribers(self):
        bc = EventBroadcaster()
        q1 = bc.subscribe()
        q2 = bc.subscribe()
        await bc.broadcast({"x": 1})
        assert not q1.empty()
        assert not q2.empty()

    @pytest.mark.asyncio
    async def test_unsubscribe_removes_queue(self):
        bc = EventBroadcaster()
        q = bc.subscribe()
        bc.unsubscribe(q)
        await bc.broadcast({"x": 1})
        assert q.empty()

    @pytest.mark.asyncio
    async def test_full_queue_drops_message_without_raising(self):
        bc = EventBroadcaster()
        q = bc.subscribe()
        for _ in range(q.maxsize):
            await bc.broadcast({"x": 1})
        # Should not raise even when queue is full
        await bc.broadcast({"x": 2})


class TestComputeLinks:
    def test_empty_returns_no_links(self):
        assert compute_links([]) == []

    def test_single_node_returns_no_links(self):
        node = {"id": 1, "embedding": [1.0, 0.0]}
        assert compute_links([node]) == []

    def test_identical_embeddings_are_linked(self):
        nodes = [
            {"id": 1, "embedding": [1.0, 0.0, 0.0]},
            {"id": 2, "embedding": [1.0, 0.0, 0.0]},
        ]
        links = compute_links(nodes)
        assert len(links) == 1
        assert links[0]["source"] == 1
        assert links[0]["target"] == 2
        assert abs(links[0]["strength"] - 1.0) < 1e-4

    def test_orthogonal_embeddings_not_linked(self):
        nodes = [
            {"id": 1, "embedding": [1.0, 0.0, 0.0]},
            {"id": 2, "embedding": [0.0, 1.0, 0.0]},
        ]
        links = compute_links(nodes, threshold=0.7)
        assert links == []

    def test_threshold_filters_weak_links(self):
        # cos([1,1,0], [1,0,0]) = 1/sqrt(2) ≈ 0.707
        nodes = [
            {"id": 1, "embedding": [1.0, 1.0, 0.0]},
            {"id": 2, "embedding": [1.0, 0.0, 0.0]},
        ]
        assert len(compute_links(nodes, threshold=0.71)) == 0
        assert len(compute_links(nodes, threshold=0.70)) == 1


class TestParseDirectiveTarget:
    def test_parses_to_field_from_json(self):
        raw = '{"to": "cmo", "action": "Draft article", "priority": "high"}'
        assert _parse_directive_target(raw) == "cmo"

    def test_returns_none_for_missing_to(self):
        raw = '{"action": "Do something", "priority": "low"}'
        assert _parse_directive_target(raw) is None

    def test_returns_none_for_invalid_json(self):
        assert _parse_directive_target("not json at all") is None

    def test_parses_from_markdown_fenced_json(self):
        raw = '```json\n{"to": "cfo", "action": "Review budget"}\n```'
        assert _parse_directive_target(raw) == "cfo"


class TestBuildFlowMatrix:
    def test_empty_flow(self):
        result = _build_flow_matrix({})
        assert result == {"edges": [], "total": 0}

    def test_single_edge(self):
        result = _build_flow_matrix({("ceo", "cmo"): 3})
        assert result["total"] == 3
        assert len(result["edges"]) == 1
        assert result["edges"][0] == {"from": "ceo", "to": "cmo", "count": 3}

    def test_multiple_edges_sorted_by_count(self):
        flow = {("ceo", "cfo"): 1, ("ceo", "cmo"): 5, ("cfo", "cto"): 2}
        result = _build_flow_matrix(flow)
        counts = [e["count"] for e in result["edges"]]
        assert counts == sorted(counts, reverse=True)


class TestBuildProviderHealth:
    def test_zero_rpm_is_idle(self):
        result = _build_provider_health("nim-1", 0, 40)
        assert result["name"] == "nim-1"
        assert result["rpm"] == 0
        assert result["max_rpm"] == 40
        assert result["status"] == "idle"

    def test_low_load_is_ok(self):
        result = _build_provider_health("groq", 10, 30)
        assert result["status"] == "ok"

    def test_high_load_is_busy(self):
        result = _build_provider_health("nim-2", 32, 40)
        assert result["status"] == "busy"

    def test_at_limit_is_limit(self):
        result = _build_provider_health("cerebras", 30, 30)
        assert result["status"] == "limit"

    def test_over_limit_is_limit(self):
        result = _build_provider_health("nim-3", 45, 40)
        assert result["status"] == "limit"

    def test_pct_calculation(self):
        result = _build_provider_health("groq", 15, 30)
        assert result["pct"] == 50.0

    def test_zero_max_rpm_does_not_divide_by_zero(self):
        result = _build_provider_health("test", 0, 0)
        assert result["pct"] == 0.0
        assert result["status"] == "idle"


class TestBuildSpendPayload:
    def test_zero_spend(self):
        assert _build_spend_payload(0.0, 5.0) == {"spent_usd": 0.0, "max_usd": 5.0, "pct": 0.0}

    def test_half_spent(self):
        result = _build_spend_payload(2.5, 5.0)
        assert result["pct"] == 50.0

    def test_over_limit_allowed(self):
        result = _build_spend_payload(6.0, 5.0)
        assert result["pct"] == 120.0

    def test_zero_max_does_not_divide_by_zero(self):
        result = _build_spend_payload(1.0, 0.0)
        assert result["pct"] == 0.0
