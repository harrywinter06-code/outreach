"""Z3 — lander route + lead capture tests."""
from unittest.mock import AsyncMock, MagicMock

import pytest


def _stub_pool(business_row=None, insert_assertion=None):
    """Mock asyncpg pool. business_row=None → 404 path."""
    pool = MagicMock()
    conn = MagicMock()

    async def _fetchrow(sql, *args):
        if "FROM businesses" in sql:
            return business_row
        return None

    async def _execute(sql, *args):
        if insert_assertion:
            insert_assertion(sql, args)
        return None

    conn.fetchrow = _fetchrow
    conn.execute = _execute
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=None)
    pool.acquire = MagicMock(return_value=cm)
    return pool


def _make_app():
    from fastapi import FastAPI
    from clawbot.business_lander import get_router
    app = FastAPI()
    app.include_router(get_router())
    return app


def test_lander_returns_404_for_unknown_business():
    from fastapi.testclient import TestClient
    from clawbot import business_lander
    business_lander.DB_POOL = _stub_pool(business_row=None)
    client = TestClient(_make_app())
    resp = client.get("/biz/nonexistent")
    assert resp.status_code == 404


def test_lander_renders_niche_price_and_payment_link_when_active():
    from fastapi.testclient import TestClient
    from clawbot import business_lander
    business_lander.DB_POOL = _stub_pool(business_row={
        "business_id": "biz_ir35",
        "name": "seed_ir35", "niche": "am i inside ir35?",
        "genome": '{"niche_question": "am i inside ir35 for my current contract?", "price_gbp": 5.0, "fulfilment_template": "ir35_quickcheck_v1"}',
        "status": "active",
        "metadata": '{"payment_link_url": "https://buy.stripe.com/test_xyz", "lander_url": "https://x/biz/biz_ir35"}',
    })
    client = TestClient(_make_app())
    resp = client.get("/biz/biz_ir35")
    assert resp.status_code == 200
    html = resp.text
    assert "am i inside ir35" in html.lower()
    assert "£5" in html
    # AI disclosure present
    assert "AI-generated" in html
    # Refund line present
    assert "refund" in html.lower()
    # The form posts to the lead endpoint
    assert 'action="/biz/biz_ir35/lead"' in html


def test_lander_returns_410_tombstone_for_killed_business():
    from fastapi.testclient import TestClient
    from clawbot import business_lander
    business_lander.DB_POOL = _stub_pool(business_row={
        "business_id": "biz_dead", "name": "old", "niche": "x",
        "genome": '{"niche_question": "x?", "price_gbp": 3.0}',
        "status": "killed",
        "metadata": "{}",
    })
    client = TestClient(_make_app())
    resp = client.get("/biz/biz_dead")
    assert resp.status_code == 410
    assert "no longer active" in resp.text


def test_lead_post_inserts_then_redirects_to_payment_link():
    from fastapi.testclient import TestClient
    from clawbot import business_lander
    captured: dict = {}

    def _assert_insert(sql, args):
        captured["sql"] = sql
        captured["args"] = args

    business_lander.DB_POOL = _stub_pool(
        business_row={
            "business_id": "biz_lead", "name": "n", "niche": "x",
            "genome": '{"niche_question": "x?", "price_gbp": 5.0}',
            "status": "active",
            "metadata": '{"payment_link_url": "https://buy.stripe.com/pay_xyz"}',
        },
        insert_assertion=_assert_insert,
    )
    client = TestClient(_make_app())
    resp = client.post(
        "/biz/biz_lead/lead",
        data={"email": "Test@Example.com", "role_summary": "freelance dev"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "https://buy.stripe.com/pay_xyz"
    # Inserted email is normalised to lowercase
    assert captured["args"][1] == "test@example.com"
    # Inputs captured (excluding email itself)
    import json as _json
    inserted_metadata = _json.loads(captured["args"][3])
    assert inserted_metadata["inputs"]["role_summary"] == "freelance dev"
    assert "email" not in inserted_metadata["inputs"]


def test_lead_post_rejects_invalid_email():
    from fastapi.testclient import TestClient
    from clawbot import business_lander
    business_lander.DB_POOL = _stub_pool(business_row={
        "business_id": "biz_x", "name": "n", "niche": "x",
        "genome": "{}", "status": "active", "metadata": "{}",
    })
    client = TestClient(_make_app())
    resp = client.post("/biz/biz_x/lead", data={"email": "not-an-email"})
    assert resp.status_code == 400
