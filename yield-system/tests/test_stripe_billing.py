from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from yield_system.config import Settings, reset_settings_for_test
from yield_system.db import connect, init_schema
from yield_system.main import build_app
from yield_system.stripe_billing import (
    _handle_checkout_completed,
    _handle_invoice_paid,
    price_to_experiment,
    refresh_price_map,
)


@pytest.fixture
def configured(tmp_path) -> Settings:
    s = Settings(
        env="dev",
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        stripe_secret_key="sk_test_x",
        stripe_webhook_secret="whsec_x",
        stripe_price_postcode="price_pc_1",
        stripe_price_sanctions="price_sa_1",
        stripe_price_webhookq="price_wh_1",
        stripe_price_email="price_em_1",
    )
    s.data_dir.mkdir(parents=True, exist_ok=True)
    s.log_dir.mkdir(parents=True, exist_ok=True)
    reset_settings_for_test(s)
    init_schema()
    refresh_price_map()
    return s


def test_price_to_experiment_resolves(configured) -> None:
    assert price_to_experiment("price_pc_1") == "postcode"
    assert price_to_experiment("price_sa_1") == "sanctions"
    assert price_to_experiment("price_unknown") is None


def test_checkout_completed_records_cre_above_5gbp(configured) -> None:
    event = {
        "id": "evt_1",
        "data": {
            "object": {
                "payment_status": "paid",
                "amount_total": 1500,
                "customer": "cus_xyz",
                "client_reference_id": "internal_abc",
                "line_items": {"data": [{"price": {"id": "price_pc_1"}}]},
            }
        },
    }
    _handle_checkout_completed(event)
    with connect() as c:
        row = c.execute("SELECT * FROM cre WHERE stripe_event_id = 'evt_1'").fetchone()
    assert row is not None
    assert row["experiment"] == "postcode"
    assert row["amount_gbp"] == 15.0


def test_checkout_under_5gbp_ignored(configured) -> None:
    event = {
        "id": "evt_small",
        "data": {
            "object": {
                "payment_status": "paid",
                "amount_total": 300,
                "customer": "cus_a",
                "line_items": {"data": [{"price": {"id": "price_pc_1"}}]},
            }
        },
    }
    _handle_checkout_completed(event)
    with connect() as c:
        row = c.execute("SELECT * FROM cre WHERE stripe_event_id = 'evt_small'").fetchone()
    assert row is None


def test_checkout_unpaid_ignored(configured) -> None:
    event = {
        "id": "evt_unpaid",
        "data": {
            "object": {
                "payment_status": "unpaid",
                "amount_total": 1500,
                "customer": "cus_a",
                "line_items": {"data": [{"price": {"id": "price_pc_1"}}]},
            }
        },
    }
    _handle_checkout_completed(event)
    with connect() as c:
        row = c.execute("SELECT * FROM cre WHERE stripe_event_id = 'evt_unpaid'").fetchone()
    assert row is None


def test_invoice_paid_records_cre(configured) -> None:
    event = {
        "id": "evt_inv",
        "data": {
            "object": {
                "amount_paid": 1000,
                "customer": "cus_b",
                "lines": {"data": [{"price": {"id": "price_sa_1"}}]},
            }
        },
    }
    _handle_invoice_paid(event)
    with connect() as c:
        row = c.execute("SELECT * FROM cre WHERE stripe_event_id = 'evt_inv'").fetchone()
    assert row is not None
    assert row["experiment"] == "sanctions"


def test_webhook_rejects_bad_signature(configured) -> None:
    client = TestClient(build_app())
    r = client.post(
        "/stripe/webhook",
        content=b'{"id": "evt_x", "type": "checkout.session.completed", "data": {}}',
        headers={"stripe-signature": "bad"},
    )
    assert r.status_code == 400


def test_webhook_503_when_secret_missing(tmp_path) -> None:
    s = Settings(
        env="dev",
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        stripe_secret_key="",
        stripe_webhook_secret="",
    )
    s.data_dir.mkdir(parents=True, exist_ok=True)
    s.log_dir.mkdir(parents=True, exist_ok=True)
    reset_settings_for_test(s)
    init_schema()
    client = TestClient(build_app())
    r = client.post(
        "/stripe/webhook",
        content=b'{}',
        headers={"stripe-signature": "anything"},
    )
    assert r.status_code == 503


def test_signup_creates_free_tier_key(configured) -> None:
    client = TestClient(build_app())
    r = client.post(
        "/signup", json={"experiment": "postcode", "email": "a@example.com"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["plan"] == "free"
    assert body["api_key"].startswith("ys_")


def test_signup_rejects_invalid_experiment(configured) -> None:
    client = TestClient(build_app())
    r = client.post(
        "/signup", json={"experiment": "not_real", "email": "a@example.com"}
    )
    assert r.status_code == 400


def test_webhook_valid_signature_processes_event(configured) -> None:
    client = TestClient(build_app())

    fake_event = {
        "id": "evt_valid",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "payment_status": "paid",
                "amount_total": 1500,
                "customer": "cus_valid",
                "client_reference_id": "internal_xyz",
                "line_items": {"data": [{"price": {"id": "price_pc_1"}}]},
            }
        },
    }
    with patch(
        "yield_system.stripe_billing.stripe.Webhook.construct_event",
        return_value=fake_event,
    ):
        r = client.post(
            "/stripe/webhook",
            content=b'{}',
            headers={"stripe-signature": "valid"},
        )
    assert r.status_code == 200
    assert r.json()["handled"] is True
