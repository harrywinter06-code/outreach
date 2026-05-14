from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from yield_system.auth import create_customer
from yield_system.experiments.sanctions import (
    fire_webhooks_for_new_entries,
    normalize_name,
    screen,
    upsert_entry,
)
from yield_system.ingest.sanctions_ofac import parse_sdn_xml
from yield_system.main import build_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(build_app())


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Vladímír Pútîn", "vladimir putin"),
        ("  KIM  JONG-UN  ", "kim jong un"),
        ("ABDUL-RAHMAN AL'AKBARI", "abdul rahman al akbari"),
    ],
)
def test_normalize_name_strips_accents_punct_case(raw: str, expected: str) -> None:
    assert normalize_name(raw) == expected


def test_upsert_idempotent_per_source_and_id() -> None:
    new1 = upsert_entry("ofac", "12345", "John Doe", aliases=["J. Doe"], program="SDN")
    new2 = upsert_entry("ofac", "12345", "John Doe", aliases=["J. Doe"], program="SDN")
    assert new1 is True
    assert new2 is False


def test_screen_returns_hit_when_normalized_match() -> None:
    upsert_entry("ofac", "S1", "Jane Smith", aliases=[], program="SDN")
    result = screen(["jane smith", "no match here"])
    assert result.requested == 2
    assert result.matched == 1
    assert result.hits[0].matched_name == "Jane Smith"
    assert result.hits[0].source == "ofac"


def test_screen_handles_unicode_variants() -> None:
    upsert_entry("ofac", "S2", "Café Owner", aliases=[], program=None)
    result = screen(["cafe owner"])
    assert result.matched == 1


def test_endpoint_screen_returns_matches(client) -> None:
    cust = create_customer("sanctions", plan="paid")
    upsert_entry("ofac", "X1", "Bad Actor", aliases=[], program="SDN")
    r = client.post(
        "/v1/sanctions/screen",
        headers={"X-API-Key": cust["api_key"]},
        json={"names": ["Bad Actor", "Good Actor"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["matched"] == 1


def test_endpoint_screen_requires_auth(client) -> None:
    r = client.post("/v1/sanctions/screen", json={"names": ["x"]})
    assert r.status_code == 401


def test_watchlist_creates_subscription(client) -> None:
    cust = create_customer("sanctions", plan="paid")
    r = client.post(
        "/v1/sanctions/watchlist",
        headers={"X-API-Key": cust["api_key"]},
        json={
            "watchlist_name": "my_list",
            "name_to_match": "John Smith",
            "webhook_url": "https://example.com/hook",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["name_normalized"] == "john smith"


def test_parse_sdn_xml_extracts_entries() -> None:
    xml = b"""<?xml version="1.0"?>
<sdnList xmlns="http://tempuri.org/sdnList.xsd">
  <sdnEntry>
    <uid>1001</uid>
    <firstName>John</firstName>
    <lastName>Doe</lastName>
    <programList><program>SDGT</program></programList>
    <akaList>
      <aka><firstName>Johnny</firstName><lastName>Doe</lastName></aka>
    </akaList>
  </sdnEntry>
</sdnList>"""
    entries = parse_sdn_xml(xml)
    assert len(entries) == 1
    assert entries[0]["name"] == "John Doe"
    assert entries[0]["program"] == "SDGT"
    assert entries[0]["aliases"] == ["Johnny Doe"]


def test_webhook_fires_only_for_subscribed_names(client) -> None:
    cust = create_customer("sanctions", plan="paid")
    client.post(
        "/v1/sanctions/watchlist",
        headers={"X-API-Key": cust["api_key"]},
        json={
            "watchlist_name": "wl",
            "name_to_match": "Target Person",
            "webhook_url": "https://callback.test/hook",
        },
    )

    class FakeResponse:
        status_code = 200

    with patch("yield_system.experiments.sanctions.httpx.post", return_value=FakeResponse()):
        fired = fire_webhooks_for_new_entries(["target person", "unrelated person"])
    assert fired == 1
