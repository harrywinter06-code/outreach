"""
Z3 — auto-bootstrap the conversion funnel for a newly-spawned business.

On every spawn, before the business cycles for the first time:
1. Create Stripe Product + Price + PaymentLink with metadata.business_id
2. Persist payment_link_url + lander_url to businesses.metadata

The lander URL is computed from settings (apex host + /biz/<id>). The
payment link's metadata carries business_id so the Stripe webhook can
route the resulting charge back to this business.

If Stripe secret is unset (e.g. fresh dev install), funnel bootstrap is
skipped with a warning — the business still spawns and cycles, just
without a payment surface. The cull loop will eventually kill it.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class FunnelBootstrapper:
    """Creates Stripe artifacts + persists URLs into business metadata."""

    def __init__(
        self,
        *,
        store: Any,
        stripe_secret_key: str = "",
        lander_base_url: str = "",
    ) -> None:
        self._store = store
        self._stripe_key = stripe_secret_key
        self._lander_base = lander_base_url.rstrip("/")

    async def bootstrap(self, *, business_id: str, genome: dict) -> dict:
        """Create funnel artifacts for one business. Returns a dict of URLs
        persisted to the business's metadata. Idempotent at the metadata
        level (re-runs overwrite the URLs); Stripe-side will create new
        Products each time so don't call twice for the same business in
        production. Z3 calls this once per spawn."""
        urls: dict[str, str] = {}
        if self._lander_base:
            urls["lander_url"] = f"{self._lander_base}/biz/{business_id}"

        if not self._stripe_key:
            logger.warning(
                "FunnelBootstrapper: STRIPE_SECRET_KEY unset — skipping Stripe artifact creation for %s",
                business_id,
            )
            if urls:
                await self._store.update_metadata(business_id=business_id, updates=urls)
            return urls

        try:
            import stripe
            niche = (genome.get("niche_question") or "personalised report")[:200]
            price_gbp = float(genome.get("price_gbp", 3.0))
            amount_pence = max(50, int(round(price_gbp * 100)))  # Stripe min £0.50
            # Product
            product = await asyncio.to_thread(
                stripe.Product.create,
                name=niche[:120],
                description=f"AI-generated personalised report on: {niche}",
                metadata={"business_id": business_id},
                api_key=self._stripe_key,
            )
            # Price
            price = await asyncio.to_thread(
                stripe.Price.create,
                product=product["id"],
                unit_amount=amount_pence,
                currency="gbp",
                api_key=self._stripe_key,
            )
            # PaymentLink — metadata propagates to the eventual Charge,
            # which is how the Z2.5c webhook routes payment → business.
            link = await asyncio.to_thread(
                stripe.PaymentLink.create,
                line_items=[{"price": price["id"], "quantity": 1}],
                metadata={"business_id": business_id},
                api_key=self._stripe_key,
            )
            urls["stripe_product_id"] = str(product["id"])
            urls["stripe_price_id"] = str(price["id"])
            urls["payment_link_url"] = str(link["url"])
            logger.info(
                "Funnel bootstrapped for %s: lander=%s, payment_link=%s",
                business_id, urls.get("lander_url"), urls["payment_link_url"],
            )
        except Exception as exc:
            logger.error(
                "FunnelBootstrapper Stripe call failed for %s: %s",
                business_id, exc, exc_info=True,
            )
            # Still persist any partial URLs (lander_url) so the business
            # has at least a surface — cycle runner can attempt payment-link
            # creation later via the stripe_create_payment_link skill.

        if urls:
            await self._store.update_metadata(business_id=business_id, updates=urls)
        return urls
