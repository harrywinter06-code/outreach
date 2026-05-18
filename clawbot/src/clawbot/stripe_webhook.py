"""
Swarm Z2.5 Task C — Stripe webhook endpoint.

POST /webhook/stripe — Stripe-signed callback. Verifies signature, parses
the event, and (for revenue-relevant events with `metadata.business_id`)
routes the £ amount to `BusinessStore.record_revenue`.

Idempotency is handled by `BusinessStore.record_revenue` via the
`(source, external_id) UNIQUE` constraint — Stripe retries are safe.

The webhook secret comes from `settings.stripe_webhook_secret`. Without
it, the endpoint accepts ALL requests in dev mode but logs a loud warning.

Module-level `BUSINESS_STORE` is set by main.py at startup. Keeps the
endpoint decoupled from FastAPI's dependency-injection system.
"""
from __future__ import annotations

import json
import logging
from typing import Any

# Module-level import so FastAPI can resolve the `Request` annotation on
# the endpoint signature. With `from __future__ import annotations` all
# annotations are strings — if Request is only imported inside _build_router,
# FastAPI's signature introspection can't find it and falls back to
# treating `request` as a query param (422 errors).
from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)

# Set by main.py once BusinessStore is instantiated. The webhook reads it
# at request time so the module can be imported before the store exists.
BUSINESS_STORE: Any | None = None


# Events that move money into the system. Charges include manual + payment-link
# + checkout-session originated charges.
_REVENUE_EVENTS = {"charge.succeeded", "payment_intent.succeeded"}
_REFUND_EVENTS = {"charge.refunded", "charge.refund.updated"}


def _build_router():
    """Build the FastAPI router. FastAPI is imported at module level (above)
    so annotation resolution works under `from __future__ import annotations`."""
    from clawbot.config import settings

    router = APIRouter()

    @router.post("/webhook/stripe")
    async def stripe_webhook(request: Request):
        payload = await request.body()
        sig_header = request.headers.get("stripe-signature", "")
        secret = settings.stripe_webhook_secret

        # Parse + verify
        if not secret:
            logger.warning(
                "STRIPE_WEBHOOK_SECRET unset — accepting unsigned webhook (DEV ONLY)"
            )
            try:
                event = json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise HTTPException(status_code=400, detail=f"invalid_payload: {exc}")
        else:
            try:
                import stripe
                # construct_event verifies the signature. We discard its return
                # value (a StripeObject that doesn't support .get()) and use the
                # plain JSON dict for downstream routing — the payload is now
                # trusted because the signature matched.
                stripe.Webhook.construct_event(payload, sig_header, secret)
                event = json.loads(payload.decode("utf-8"))
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                logger.warning("Stripe webhook payload parse failed: %s", exc)
                raise HTTPException(status_code=400, detail="invalid_payload")
            except Exception as exc:
                # stripe.error.SignatureVerificationError is the expected case.
                logger.warning("Stripe webhook signature verify failed: %s", exc)
                raise HTTPException(status_code=400, detail="signature_invalid")

        result = await _route_event(event)
        return result

    return router


async def _route_event(event: dict) -> dict:
    """Pure dispatch: examine event type, route to BusinessStore.record_revenue
    when applicable. Returns a JSON-serialisable result for the response body.

    Extracted from the endpoint so tests can call it without spinning up
    FastAPI.
    """
    if BUSINESS_STORE is None:
        logger.error("Stripe webhook: BUSINESS_STORE not wired — dropping event")
        return {"ok": False, "routed": False, "reason": "store_unavailable"}

    event_type = event.get("type", "")
    obj = (event.get("data") or {}).get("object") or {}
    biz_id = (obj.get("metadata") or {}).get("business_id")

    if event_type in _REVENUE_EVENTS:
        if not biz_id:
            logger.warning(
                "Stripe %s id=%s has no metadata.business_id — drop",
                event_type, obj.get("id"),
            )
            return {"ok": True, "routed": False, "reason": "no_business_id"}
        currency = str(obj.get("currency") or "").lower()
        if currency and currency != "gbp":
            return {"ok": True, "routed": False, "reason": f"non_gbp:{currency}"}
        # Stripe uses minor units (pence for GBP)
        amount_gbp = float(obj.get("amount") or 0) / 100.0
        if amount_gbp <= 0:
            return {"ok": True, "routed": False, "reason": "zero_amount"}
        inserted = await BUSINESS_STORE.record_revenue(
            business_id=biz_id,
            amount_gbp=amount_gbp,
            source="stripe",
            external_id=str(obj.get("id") or event.get("id")),
            is_self_paid=False,
            metadata={
                "stripe_event_id": event.get("id"),
                "stripe_event_type": event_type,
            },
        )
        logger.info(
            "Stripe webhook → business_revenue: biz=%s amount=£%.2f inserted=%s",
            biz_id, amount_gbp, inserted,
        )
        return {"ok": True, "routed": True, "inserted": inserted}

    if event_type in _REFUND_EVENTS:
        if not biz_id:
            return {"ok": True, "routed": False, "reason": "no_business_id"}
        refund_amount = float(obj.get("amount_refunded") or obj.get("amount") or 0) / 100.0
        if refund_amount <= 0:
            return {"ok": True, "routed": False, "reason": "zero_amount"}
        inserted = await BUSINESS_STORE.record_revenue(
            business_id=biz_id,
            amount_gbp=refund_amount,
            source="stripe",
            external_id=f"refund_{obj.get('id')}",
            is_refund=True,
            metadata={
                "stripe_event_id": event.get("id"),
                "stripe_event_type": event_type,
            },
        )
        logger.info(
            "Stripe webhook → refund: biz=%s amount=£%.2f inserted=%s",
            biz_id, refund_amount, inserted,
        )
        return {"ok": True, "routed": True, "inserted": inserted, "refund": True}

    # Unknown event type — ack so Stripe doesn't retry forever.
    return {"ok": True, "routed": False, "reason": f"unhandled_event:{event_type}"}


def get_router():
    """Public accessor — called by dashboard create_app to mount the route."""
    return _build_router()
