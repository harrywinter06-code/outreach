from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from yield_system.auth import create_customer
from yield_system.experiments.email_score import DnsLookup, score
from yield_system.main import build_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(build_app())


def test_score_grade_a_for_full_stack() -> None:
    lookup = DnsLookup(
        mx=["mx1.example.com"],
        spf="v=spf1 include:_spf.google.com -all",
        dmarc="v=DMARC1; p=reject; rua=mailto:dmarc@example.com",
        bimi="v=BIMI1; l=https://example.com/logo.svg",
        dnssec=True,
    )
    grade, points, recs = score(lookup)
    assert grade == "A"
    assert points == 100
    assert recs == []


def test_score_grade_f_for_no_records() -> None:
    grade, points, recs = score(
        DnsLookup(mx=[], spf=None, dmarc=None, bimi=None, dnssec=False)
    )
    assert grade == "F"
    assert points == 0
    assert len(recs) >= 4


def test_score_penalizes_permissive_spf() -> None:
    grade, _points, recs = score(
        DnsLookup(
            mx=["mx.example.com"],
            spf="v=spf1 include:_spf.google.com +all",
            dmarc="v=DMARC1; p=reject",
            bimi=None,
            dnssec=False,
        )
    )
    assert "too permissive" in " ".join(recs).lower()
    assert grade in {"C", "D"}


def test_score_dmarc_p_none_recommended_upgrade() -> None:
    _grade, _points, recs = score(
        DnsLookup(
            mx=["mx.example.com"],
            spf="v=spf1 -all",
            dmarc="v=DMARC1; p=none",
            bimi=None,
            dnssec=False,
        )
    )
    assert any("p=none" in r for r in recs)


def test_endpoint_400_for_invalid_domain(client) -> None:
    cust = create_customer("email", plan="paid")
    r = client.get("/v1/domain/notadomain", headers={"X-API-Key": cust["api_key"]})
    assert r.status_code == 400


def test_endpoint_returns_score_with_mocked_dns(client) -> None:
    cust = create_customer("email", plan="paid")
    fake = DnsLookup(
        mx=["mx.example.com"],
        spf="v=spf1 -all",
        dmarc="v=DMARC1; p=quarantine",
        bimi=None,
        dnssec=True,
    )
    with patch("yield_system.experiments.email_score.lookup", return_value=fake):
        r = client.get(
            "/v1/domain/example.com", headers={"X-API-Key": cust["api_key"]}
        )
    assert r.status_code == 200
    body = r.json()
    assert body["domain"] == "example.com"
    assert body["score"] in {"A", "B", "C"}
    assert body["dnssec"] is True
