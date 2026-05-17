import asyncio
import json as _json

from clawbot.shadow_fixtures import lookup_fixture, FIXTURES
from clawbot.shadow_ctx import make_shadow_ctx


def test_stripe_create_product_fixture_matches_real_shape():
    fix = lookup_fixture("POST", "https://api.stripe.com/v1/products")
    assert fix is not None
    assert fix["status"] == 200
    body = fix["json"]
    # Real Stripe response shape — no "data" wrapper, id at top level
    assert "id" in body
    assert body["id"].startswith("prod_")
    assert "object" in body and body["object"] == "product"
    assert "data" not in body  # this catches hallucinated wrappers


def test_x_post_fixture_has_data_wrapper():
    fix = lookup_fixture("POST", "https://api.twitter.com/2/tweets")
    assert fix is not None
    # X v2 DOES use a data wrapper
    assert "data" in fix["json"]
    assert "id" in fix["json"]["data"]


def test_shadow_ctx_http_returns_fixture_when_matched():
    ctx = make_shadow_ctx(caller_id="t", budget_usd=0)
    r = asyncio.run(ctx.http.post(
        "https://api.stripe.com/v1/products",
        json={"name": "x", "description": "y"},
    ))
    body = r.get("text", "")
    parsed = _json.loads(body)
    assert parsed["id"].startswith("prod_")


def test_shadow_ctx_falls_back_to_empty_on_unmatched_url():
    ctx = make_shadow_ctx(caller_id="t", budget_usd=0)
    r = asyncio.run(ctx.http.get("https://unknown.example/foo"))
    assert r["status"] == 200
    assert r["text"] == ""
