"""Z3 — FunnelBootstrapper tests."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_bootstrap_persists_lander_url_when_stripe_key_unset():
    """Even without Stripe configured, the lander URL must be persisted
    so the business has at least a public surface for content links."""
    from clawbot.business_funnel import FunnelBootstrapper
    store = MagicMock()
    store.update_metadata = AsyncMock()
    fb = FunnelBootstrapper(
        store=store, stripe_secret_key="",
        lander_base_url="https://example.test",
    )
    urls = await fb.bootstrap(
        business_id="biz_xyz",
        genome={"niche_question": "x?", "price_gbp": 3.0},
    )
    assert urls.get("lander_url") == "https://example.test/biz/biz_xyz"
    store.update_metadata.assert_awaited_once()
    args = store.update_metadata.call_args.kwargs
    assert args["updates"]["lander_url"] == "https://example.test/biz/biz_xyz"


@pytest.mark.asyncio
async def test_bootstrap_creates_stripe_product_price_paymentlink_with_business_id_metadata():
    """The PaymentLink MUST include metadata.business_id — that's how the
    webhook routes the eventual charge back to the right business."""
    from clawbot.business_funnel import FunnelBootstrapper
    store = MagicMock()
    store.update_metadata = AsyncMock()
    fake_product = {"id": "prod_test"}
    fake_price = {"id": "price_test"}
    fake_link = {"id": "plink_test", "url": "https://buy.stripe.com/test"}

    with patch("stripe.Product.create", return_value=fake_product) as mp, \
         patch("stripe.Price.create", return_value=fake_price) as mpr, \
         patch("stripe.PaymentLink.create", return_value=fake_link) as ml:
        fb = FunnelBootstrapper(
            store=store, stripe_secret_key="sk_test_xxx",
            lander_base_url="https://x.test",
        )
        urls = await fb.bootstrap(
            business_id="biz_42",
            genome={"niche_question": "what?", "price_gbp": 5.0,
                    "fulfilment_template": "ir35_quickcheck_v1"},
        )
    # Product: name from niche, metadata.business_id, sk_test passed as api_key
    pkwargs = mp.call_args.kwargs
    assert pkwargs["metadata"]["business_id"] == "biz_42"
    assert pkwargs["api_key"] == "sk_test_xxx"
    # Price: 500 pence (£5), gbp
    prkwargs = mpr.call_args.kwargs
    assert prkwargs["unit_amount"] == 500
    assert prkwargs["currency"] == "gbp"
    # PaymentLink: metadata.business_id MUST be present
    lkwargs = ml.call_args.kwargs
    assert lkwargs["metadata"]["business_id"] == "biz_42"
    # All persisted to business metadata
    assert urls["stripe_product_id"] == "prod_test"
    assert urls["payment_link_url"] == "https://buy.stripe.com/test"
    assert urls["lander_url"] == "https://x.test/biz/biz_42"


@pytest.mark.asyncio
async def test_bootstrap_clamps_amount_at_stripe_minimum():
    """Stripe rejects amount_pence < 50 for GBP. Genome with very low price
    must be clamped to the floor."""
    from clawbot.business_funnel import FunnelBootstrapper
    store = MagicMock()
    store.update_metadata = AsyncMock()
    with patch("stripe.Product.create", return_value={"id": "p"}), \
         patch("stripe.Price.create", return_value={"id": "pr"}) as mpr, \
         patch("stripe.PaymentLink.create", return_value={"id": "l", "url": "u"}):
        fb = FunnelBootstrapper(store=store, stripe_secret_key="sk_test_x")
        await fb.bootstrap(business_id="biz_cheap",
                           genome={"niche_question": "x?", "price_gbp": 0.10})
    assert mpr.call_args.kwargs["unit_amount"] == 50


@pytest.mark.asyncio
async def test_bootstrap_persists_partial_urls_when_stripe_fails():
    """Stripe call raises → still persist lander_url + any successful URLs.
    The business stays alive; cycle runner may re-attempt later."""
    from clawbot.business_funnel import FunnelBootstrapper
    store = MagicMock()
    store.update_metadata = AsyncMock()
    with patch("stripe.Product.create", side_effect=RuntimeError("stripe down")):
        fb = FunnelBootstrapper(
            store=store, stripe_secret_key="sk_test_x",
            lander_base_url="https://x.test",
        )
        urls = await fb.bootstrap(
            business_id="biz_partial",
            genome={"niche_question": "x?", "price_gbp": 3.0},
        )
    # lander_url survives the Stripe failure
    assert urls.get("lander_url") == "https://x.test/biz/biz_partial"
    store.update_metadata.assert_awaited_once()
