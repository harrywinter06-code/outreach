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
            "id": "ch_3OabcDEF12345",  # real-looking Stripe charge ID
            "amount": 500,  # 500 pence = £5.00
            "currency": "gbp",
            "billing_details": {"email": "real.customer@somecompany.com"},
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
    assert call["external_id"] == "ch_3OabcDEF12345"
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


def test_signed_post_returns_dict_not_stripe_object_to_route_event(monkeypatch):
    """Regression: stripe.Webhook.construct_event returns a StripeObject
    that doesn't support .get(). The endpoint must coerce to dict (via
    json.loads on the raw payload) before passing to _route_event."""
    import json as _json
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from clawbot import stripe_webhook
    from clawbot.config import settings

    # Wire a fake secret + mock store
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test_only")
    mock_store = MagicMock()
    mock_store.record_revenue = AsyncMock(return_value=True)
    prior = stripe_webhook.BUSINESS_STORE
    stripe_webhook.BUSINESS_STORE = mock_store

    try:
        app = FastAPI()
        app.include_router(stripe_webhook.get_router())
        client = TestClient(app)

        import hmac, hashlib, time
        event = {
            "id": "evt_signed_test", "object": "event",
            "type": "charge.succeeded",
            "data": {"object": {
                "id": "ch_test_signed", "object": "charge",
                "amount": 250, "currency": "gbp",
                "metadata": {"business_id": "biz_xyz"},
            }},
        }
        payload = _json.dumps(event, separators=(",", ":")).encode()
        ts = int(time.time())
        signed = f"{ts}.".encode() + payload
        sig = hmac.new(b"whsec_test_only", signed, hashlib.sha256).hexdigest()
        header = f"t={ts},v1={sig}"

        response = client.post(
            "/webhook/stripe", content=payload,
            headers={"stripe-signature": header, "content-type": "application/json"},
        )
        assert response.status_code == 200, (
            f"signed POST must return 200, not {response.status_code}: {response.text}"
        )
        body = response.json()
        assert body["routed"] is True, f"signed event must route: {body}"
        mock_store.record_revenue.assert_awaited_once()
    finally:
        stripe_webhook.BUSINESS_STORE = prior


def test_webhook_endpoint_binds_request_correctly():
    """Regression: `from __future__ import annotations` makes annotations
    strings. If Request is imported inside the router builder, FastAPI
    can't resolve the annotation and treats `request` as a query param,
    returning 422 on any POST.

    Verify the endpoint accepts a POST without complaining about missing
    query params (we expect a 400 for the unsigned/invalid body, NOT 422).
    """
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from clawbot.stripe_webhook import get_router
    app = FastAPI()
    app.include_router(get_router())
    client = TestClient(app)
    # Send an unsigned, empty-body POST. With STRIPE_WEBHOOK_SECRET unset
    # in test env, this should hit the dev-mode JSON parse path and either
    # succeed-with-routed-False (if "{}") or 400 for invalid payload —
    # but NOT 422 (missing param) which would indicate the annotation bug.
    response = client.post("/webhook/stripe", content=b"{}")
    assert response.status_code != 422, (
        f"422 means FastAPI didn't bind Request — annotation regression. Body: {response.text}"
    )


@pytest.mark.asyncio
async def test_charge_with_operator_email_tagged_as_self_paid(mock_store, monkeypatch):
    """Z3: operator's test purchases must be tagged is_self_paid=True so
    they don't inflate the fitness signal."""
    from clawbot.stripe_webhook import _route_event
    monkeypatch.setenv("OPERATOR_EMAIL", "harrywinter06@gmail.com")
    event = {
        "id": "evt_self", "type": "charge.succeeded",
        "data": {"object": {
            "id": "ch_self", "amount": 500, "currency": "gbp",
            "billing_details": {"email": "harrywinter06@gmail.com"},
            "metadata": {"business_id": "biz_x"},
        }},
    }
    result = await _route_event(event)
    assert result["routed"] is True
    assert result["self_paid"] is True
    call = mock_store.record_revenue.call_args.kwargs
    assert call["is_self_paid"] is True


@pytest.mark.asyncio
async def test_charge_with_unknown_email_not_self_paid(mock_store, monkeypatch):
    from clawbot.stripe_webhook import _route_event
    monkeypatch.setenv("OPERATOR_EMAIL", "harrywinter06@gmail.com")
    event = {
        "id": "evt_real", "type": "charge.succeeded",
        "data": {"object": {
            "id": "ch_real_3OabcDEF12345", "amount": 500, "currency": "gbp",
            "billing_details": {"email": "stranger@elsewhere.com"},
            "metadata": {"business_id": "biz_x"},
        }},
    }
    result = await _route_event(event)
    assert result["routed"] is True
    assert result["self_paid"] is False
    call = mock_store.record_revenue.call_args.kwargs
    assert call["is_self_paid"] is False


@pytest.mark.asyncio
async def test_charge_with_example_com_email_tagged_synthetic(mock_store, monkeypatch):
    """Z5b: test-shaped emails (test_buyer@example.com etc.) MUST be flagged
    as is_self_paid=True so they don't pollute the dashboard's 'real revenue'
    KPI. Regression test for the bug where £10 of operator-test webhook
    smoke-tests showed up as real revenue."""
    from clawbot.stripe_webhook import _route_event
    monkeypatch.setenv("OPERATOR_EMAIL", "harrywinter06@gmail.com")
    for fake_email in [
        "test_buyer@example.com",
        "real_buyer@example.org",
        "anybody@example.net",
        "stress_test@test.com",
        "myself@bot.veriflowlabs.co.uk",
    ]:
        mock_store.record_revenue.reset_mock()
        event = {
            "id": f"evt_test_{fake_email}", "type": "charge.succeeded",
            "data": {"object": {
                "id": f"ch_real_{fake_email}", "amount": 500, "currency": "gbp",
                "billing_details": {"email": fake_email},
                "metadata": {"business_id": "biz_x"},
            }},
        }
        result = await _route_event(event)
        assert result["routed"] is True
        assert result["self_paid"] is True, f"failed to flag synthetic email {fake_email!r}"
        call = mock_store.record_revenue.call_args.kwargs
        assert call["is_self_paid"] is True


@pytest.mark.asyncio
async def test_charge_with_test_pattern_external_id_tagged_synthetic(mock_store, monkeypatch):
    """Even with a real-looking billing email, charge IDs matching our
    smoke-test prefixes (ch_z3_*, ch_smoke_*, ch_test_*) are operator
    smoke-tests by definition. Catch them at the external_id layer."""
    from clawbot.stripe_webhook import _route_event
    monkeypatch.setenv("OPERATOR_EMAIL", "harrywinter06@gmail.com")
    for synthetic_id in ["ch_z3_real_123", "ch_smoke_999", "ch_signed_abc",
                          "ch_test_xyz", "ch_https_888"]:
        mock_store.record_revenue.reset_mock()
        event = {
            "id": f"evt_{synthetic_id}", "type": "charge.succeeded",
            "data": {"object": {
                "id": synthetic_id, "amount": 500, "currency": "gbp",
                "billing_details": {"email": "looks-real@somecompany.com"},
                "metadata": {"business_id": "biz_x"},
            }},
        }
        result = await _route_event(event)
        assert result["self_paid"] is True, f"failed to flag synthetic id {synthetic_id!r}"


@pytest.mark.asyncio
async def test_charge_with_empty_billing_email_tagged_synthetic(mock_store):
    """No billing email = Stripe CLI test event or webhook test. Default to
    synthetic so an absent customer doesn't get counted as real revenue."""
    from clawbot.stripe_webhook import _route_event
    event = {
        "id": "evt_no_email", "type": "charge.succeeded",
        "data": {"object": {
            "id": "ch_real_no_email_999", "amount": 500, "currency": "gbp",
            "billing_details": {},
            "metadata": {"business_id": "biz_x"},
        }},
    }
    result = await _route_event(event)
    assert result["self_paid"] is True


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
