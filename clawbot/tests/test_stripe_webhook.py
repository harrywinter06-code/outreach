"""Z2.5c — Stripe webhook routing tests.

We test the `_route_event` pure dispatch directly to avoid spinning up
FastAPI in unit tests. Signature verification is the FastAPI endpoint's
concern and is exercised by the integration-style test that uses the
TestClient.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_store():
    store = MagicMock()
    store.record_revenue = AsyncMock(return_value=True)
    return store


@pytest.fixture(autouse=True)
def wire_store(mock_store):
    """Set the module-level BUSINESS_STORE before each test, restore after."""
    from clawbot import stripe_webhook
    prior = stripe_webhook.BUSINESS_STORE
    stripe_webhook.BUSINESS_STORE = mock_store
    yield
    stripe_webhook.BUSINESS_STORE = prior


@pytest.mark.asyncio
async def test_charge_succeeded_with_business_id_routes_to_record_revenue(mock_store):
    from clawbot.stripe_webhook import _route_event
    event = {
        "id": "evt_1",
        "type": "charge.succeeded",
        "data": {"object": {
            "id": "ch_abc",
            "amount": 500,  # 500 pence = £5.00
            "currency": "gbp",
            "metadata": {"business_id": "biz_council_42"},
        }},
    }
    result = await _route_event(event)
    assert result["routed"] is True
    mock_store.record_revenue.assert_awaited_once()
    call = mock_store.record_revenue.call_args.kwargs
    assert call["business_id"] == "biz_council_42"
    assert call["amount_gbp"] == 5.0
    assert call["source"] == "stripe"
    assert call["external_id"] == "ch_abc"
    assert call["is_self_paid"] is False


@pytest.mark.asyncio
async def test_charge_without_business_id_is_dropped(mock_store):
    """Self-pay or manual-Stripe-dashboard charges have no metadata.business_id
    and MUST NOT be recorded as business revenue."""
    from clawbot.stripe_webhook import _route_event
    event = {
        "id": "evt_2",
        "type": "charge.succeeded",
        "data": {"object": {
            "id": "ch_def",
            "amount": 1000,
            "currency": "gbp",
            "metadata": {},
        }},
    }
    result = await _route_event(event)
    assert result["routed"] is False
    assert result["reason"] == "no_business_id"
    mock_store.record_revenue.assert_not_called()


@pytest.mark.asyncio
async def test_non_gbp_currency_is_dropped(mock_store):
    from clawbot.stripe_webhook import _route_event
    event = {
        "id": "evt_3",
        "type": "charge.succeeded",
        "data": {"object": {
            "id": "ch_usd", "amount": 500, "currency": "usd",
            "metadata": {"business_id": "biz_x"},
        }},
    }
    result = await _route_event(event)
    assert result["routed"] is False
    assert "non_gbp" in result["reason"]
    mock_store.record_revenue.assert_not_called()


@pytest.mark.asyncio
async def test_zero_amount_is_dropped(mock_store):
    """Defensive: don't write zero-amount rows even if Stripe sends one."""
    from clawbot.stripe_webhook import _route_event
    event = {
        "id": "evt_4",
        "type": "charge.succeeded",
        "data": {"object": {
            "id": "ch_zero", "amount": 0, "currency": "gbp",
            "metadata": {"business_id": "biz_x"},
        }},
    }
    result = await _route_event(event)
    assert result["routed"] is False
    assert result["reason"] == "zero_amount"
    mock_store.record_revenue.assert_not_called()


@pytest.mark.asyncio
async def test_refund_event_routes_with_is_refund_true(mock_store):
    from clawbot.stripe_webhook import _route_event
    event = {
        "id": "evt_5",
        "type": "charge.refunded",
        "data": {"object": {
            "id": "ch_ref", "amount": 500, "amount_refunded": 500,
            "currency": "gbp",
            "metadata": {"business_id": "biz_council_42"},
        }},
    }
    result = await _route_event(event)
    assert result["routed"] is True
    assert result.get("refund") is True
    call = mock_store.record_revenue.call_args.kwargs
    assert call["is_refund"] is True
    assert call["external_id"].startswith("refund_")
    assert call["amount_gbp"] == 5.0


@pytest.mark.asyncio
async def test_unhandled_event_type_is_acked_without_routing(mock_store):
    """Stripe sends many event types we don't care about. Don't 500 — ack
    with a reason so Stripe doesn't retry forever."""
    from clawbot.stripe_webhook import _route_event
    event = {
        "id": "evt_6",
        "type": "customer.created",  # we don't handle this
        "data": {"object": {"id": "cus_x"}},
    }
    result = await _route_event(event)
    assert result["ok"] is True
    assert result["routed"] is False
    assert "unhandled_event" in result["reason"]
    mock_store.record_revenue.assert_not_called()


@pytest.mark.asyncio
async def test_payment_intent_succeeded_also_routes(mock_store):
    """Payment Intents (used by Checkout Sessions) hit the same path."""
    from clawbot.stripe_webhook import _route_event
    event = {
        "id": "evt_7",
        "type": "payment_intent.succeeded",
        "data": {"object": {
            "id": "pi_abc", "amount": 300, "currency": "gbp",
            "metadata": {"business_id": "biz_ir35"},
        }},
    }
    result = await _route_event(event)
    assert result["routed"] is True
    call = mock_store.record_revenue.call_args.kwargs
    assert call["business_id"] == "biz_ir35"
    assert call["amount_gbp"] == 3.0


@pytest.mark.asyncio
async def test_route_returns_store_unavailable_when_business_store_not_wired():
    """If main.py never sets BUSINESS_STORE (misconfig), the webhook must
    fail loudly rather than silently dropping payment data."""
    from clawbot import stripe_webhook
    stripe_webhook.BUSINESS_STORE = None  # override the fixture
    from clawbot.stripe_webhook import _route_event
    event = {"id": "evt_8", "type": "charge.succeeded", "data": {"object": {}}}
    result = await _route_event(event)
    assert result["ok"] is False
    assert result["reason"] == "store_unavailable"
