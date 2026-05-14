import pytest
from fastapi.testclient import TestClient

from yield_system.auth import create_customer, upgrade_customer
from yield_system.db import connect
from yield_system.experiments.postcode import (
    PostcodeData,
    ensure_table,
    lookup_postcode,
    normalize_postcode,
)
from yield_system.main import build_app


@pytest.fixture
def client() -> TestClient:
    ensure_table()
    return TestClient(build_app())


@pytest.fixture
def seeded() -> None:
    ensure_table()
    with connect() as c:
        c.execute(
            "INSERT OR REPLACE INTO postcodes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "SW1A1AA", 51.5010, -0.1416, "E01000001", "E02000001",
                "Westminster", "London", 8, 4, 12.5,
            ),
        )
        c.execute(
            "INSERT OR REPLACE INTO postcodes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "M11AA", 53.4808, -2.2426, "E01005066", "E02001033",
                "Manchester", "North West", 2, 1, 56.8,
            ),
        )


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("SW1A 1AA", "SW1A1AA"),
        ("sw1a 1aa", "SW1A1AA"),
        ("  M1 1AA  ", "M11AA"),
        ("EC1A1BB", "EC1A1BB"),
    ],
)
def test_normalize_postcode_accepts_valid_uk_formats(raw: str, expected: str) -> None:
    assert normalize_postcode(raw) == expected


@pytest.mark.parametrize("raw", ["XX", "12345", "ABCD 1234", "", "SW1A 1A"])
def test_normalize_postcode_rejects_invalid_formats(raw: str) -> None:
    assert normalize_postcode(raw) is None


def test_lookup_returns_typed_data_when_postcode_seeded(seeded) -> None:
    data = lookup_postcode("SW1A1AA")
    assert isinstance(data, PostcodeData)
    assert data.region == "London"
    assert data.imd_decile == 8


def test_lookup_returns_none_for_unknown_postcode(seeded) -> None:
    assert lookup_postcode("ZZ99ZZ") is None


def test_endpoint_returns_404_for_unknown_postcode(client, seeded) -> None:
    customer = create_customer("postcode", email="a@b.com", plan="free")
    r = client.get("/v1/postcode/ZZ99ZZ", headers={"X-API-Key": customer["api_key"]})
    assert r.status_code == 404


def test_endpoint_returns_400_for_malformed_postcode(client, seeded) -> None:
    customer = create_customer("postcode", email="a@b.com", plan="free")
    r = client.get("/v1/postcode/notapostcode", headers={"X-API-Key": customer["api_key"]})
    assert r.status_code == 400


def test_endpoint_returns_401_without_api_key(client, seeded) -> None:
    r = client.get("/v1/postcode/SW1A1AA")
    assert r.status_code == 401


def test_endpoint_returns_401_with_invalid_api_key(client, seeded) -> None:
    r = client.get("/v1/postcode/SW1A1AA", headers={"X-API-Key": "ys_invalid"})
    assert r.status_code == 401


def test_endpoint_returns_403_when_key_belongs_to_other_experiment(client, seeded) -> None:
    other = create_customer("sanctions", email="x@y.com", plan="paid")
    r = client.get("/v1/postcode/SW1A1AA", headers={"X-API-Key": other["api_key"]})
    assert r.status_code == 403


def test_endpoint_returns_data_for_valid_request(client, seeded) -> None:
    customer = create_customer("postcode", email="a@b.com", plan="paid")
    r = client.get("/v1/postcode/SW1A 1AA", headers={"X-API-Key": customer["api_key"]})
    assert r.status_code == 200
    body = r.json()
    assert body["postcode"] == "SW1A1AA"
    assert body["region"] == "London"
    assert body["imd_decile"] == 8


def test_free_tier_daily_limit_enforced(client, seeded) -> None:
    customer = create_customer("postcode", email="a@b.com", plan="free")
    headers = {"X-API-Key": customer["api_key"]}
    for _ in range(100):
        r = client.get("/v1/postcode/SW1A1AA", headers=headers)
        assert r.status_code == 200
    r = client.get("/v1/postcode/SW1A1AA", headers=headers)
    assert r.status_code == 429


def test_paid_tier_not_rate_limited(client, seeded) -> None:
    customer = create_customer("postcode", email="a@b.com", plan="free")
    upgrade_customer("cus_stripe_123", customer["customer_id"])
    with connect() as c:
        c.execute(
            "UPDATE customers SET plan = 'paid' WHERE id = ?",
            (customer["customer_id"],),
        )
    headers = {"X-API-Key": customer["api_key"]}
    for _ in range(150):
        r = client.get("/v1/postcode/SW1A1AA", headers=headers)
        assert r.status_code == 200
