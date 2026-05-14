import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from yield_system.experiments.webhook_q import generate_token
from yield_system.main import build_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(build_app())


def test_generate_token_unique() -> None:
    assert len({generate_token() for _ in range(50)}) == 50


def test_create_project_returns_token(client) -> None:
    r = client.post("/v1/webhookq/projects")
    assert r.status_code == 201
    body = r.json()
    assert body["token"].startswith("whq_")
    assert body["ingress_url"].endswith(body["token"])


def test_ingress_stores_payload(client) -> None:
    token = generate_token()
    r = client.post(
        f"/v1/webhookq/ingress/{token}",
        content=b'{"event": "test"}',
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "stored"
    assert len(body["body_sha256"]) == 64


def test_ingress_dedup_returns_409_on_duplicate(client) -> None:
    token = generate_token()
    payload = b'{"event": "dup_test"}'
    r1 = client.post(f"/v1/webhookq/ingress/{token}", content=payload)
    r2 = client.post(f"/v1/webhookq/ingress/{token}", content=payload)
    assert r1.status_code == 200
    assert r2.status_code == 409
    assert r2.json()["status"] == "duplicate"


def test_ingress_idempotency_key_separates_otherwise_identical(client) -> None:
    token = generate_token()
    payload = b'{"event": "same"}'
    r1 = client.post(
        f"/v1/webhookq/ingress/{token}",
        content=payload,
        headers={"Idempotency-Key": "k1"},
    )
    r2 = client.post(
        f"/v1/webhookq/ingress/{token}",
        content=payload,
        headers={"Idempotency-Key": "k2"},
    )
    assert r1.status_code == 200
    assert r2.status_code == 200


def test_list_events_paginates(client) -> None:
    token = generate_token()
    for i in range(5):
        client.post(
            f"/v1/webhookq/ingress/{token}",
            content=json.dumps({"i": i}).encode(),
        )
    r = client.get(f"/v1/webhookq/events/{token}?limit=3")
    assert r.status_code == 200
    body = r.json()
    assert len(body["events"]) == 3
    assert body["next_cursor"] is not None

    r2 = client.get(f"/v1/webhookq/events/{token}?cursor={body['next_cursor']}&limit=3")
    body2 = r2.json()
    assert len(body2["events"]) == 2
    assert body2["next_cursor"] is None


def test_list_events_isolated_by_token(client) -> None:
    t1 = generate_token()
    t2 = generate_token()
    client.post(f"/v1/webhookq/ingress/{t1}", content=b'{"a": 1}')
    client.post(f"/v1/webhookq/ingress/{t2}", content=b'{"b": 2}')
    r1 = client.get(f"/v1/webhookq/events/{t1}")
    r2 = client.get(f"/v1/webhookq/events/{t2}")
    assert len(r1.json()["events"]) == 1
    assert len(r2.json()["events"]) == 1
    assert r1.json()["events"][0]["body_sha256"] != r2.json()["events"][0]["body_sha256"]


def test_replay_delivers_to_target(client) -> None:
    token = generate_token()
    ingress_r = client.post(
        f"/v1/webhookq/ingress/{token}", content=b'{"x": 1}'
    )
    assert ingress_r.status_code == 200
    events_r = client.get(f"/v1/webhookq/events/{token}")
    event_id = events_r.json()["events"][0]["id"]

    class FakeResp:
        status_code = 200

    with patch("yield_system.experiments.webhook_q.httpx.post", return_value=FakeResp()):
        r = client.post(
            f"/v1/webhookq/egress/{token}",
            json={"event_ids": [event_id], "target_url": "https://target.test/hook"},
        )
    assert r.status_code == 200
    assert r.json()["delivered"] == 1
    assert r.json()["failed"] == 0


def test_replay_records_failures_separately(client) -> None:
    token = generate_token()
    client.post(f"/v1/webhookq/ingress/{token}", content=b'{"y": 2}')
    events_r = client.get(f"/v1/webhookq/events/{token}")
    event_id = events_r.json()["events"][0]["id"]

    class FakeResp:
        status_code = 500

    with patch("yield_system.experiments.webhook_q.httpx.post", return_value=FakeResp()):
        r = client.post(
            f"/v1/webhookq/egress/{token}",
            json={"event_ids": [event_id], "target_url": "https://target.test/hook"},
        )
    assert r.json()["delivered"] == 0
    assert r.json()["failed"] == 1
