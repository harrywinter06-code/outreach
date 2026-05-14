"""Stripe webhook receiver — converts checkout/subscription events into CREs.

CRE (Confirmed Revenue Event) definition per directive §6:
- A completed Stripe payment ≥£5 from a non-self customer attributed to an experiment.

Pending invoices and free-tier signups do NOT count.
"""
import stripe
from fastapi import APIRouter, HTTPException, Request, status

from yield_system.auth import (
    create_paid_customer,
    downgrade_customer,
    lookup_customer_by_email,
    upgrade_customer,
)
from yield_system.config import settings
from yield_system.log import record_cre

router = APIRouter(prefix="/stripe", tags=["stripe"])

_PRICE_TO_EXPERIMENT: dict[str, str] = {}


def price_to_experiment(price_id: str) -> str | None:
    return _PRICE_TO_EXPERIMENT.get(price_id)


def refresh_price_map() -> None:
    s = settings()
    if s.stripe_secret_key:
        stripe.api_key = s.stripe_secret_key
    _PRICE_TO_EXPERIMENT.clear()
    if s.stripe_price_sanctions:
        _PRICE_TO_EXPERIMENT[s.stripe_price_sanctions] = "sanctions"
    if s.stripe_price_postcode:
        _PRICE_TO_EXPERIMENT[s.stripe_price_postcode] = "postcode"
    if s.stripe_price_webhookq:
        _PRICE_TO_EXPERIMENT[s.stripe_price_webhookq] = "webhookq"
    if s.stripe_price_email:
        _PRICE_TO_EXPERIMENT[s.stripe_price_email] = "email"


@router.post("/webhook")
async def stripe_webhook(request: Request) -> dict:
    refresh_price_map()
    raw = await request.body()
    sig = request.headers.get("stripe-signature", "")
    secret = settings().stripe_webhook_secret
    if not secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "stripe not configured")
    try:
        event = stripe.Webhook.construct_event(raw, sig, secret)
    except (stripe.SignatureVerificationError, ValueError) as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"bad signature: {e}") from e

    handler = _HANDLERS.get(event["type"])
    if handler is None:
        return {"received": event["type"], "handled": False}
    handler(event)
    return {"received": event["type"], "handled": True}


def _fetch_line_items(obj: dict) -> list[dict]:
    """
    Stripe doesn't expand line_items in the webhook payload by default.
    Prefer the API fetch; fall back to whatever is embedded in obj (useful in tests).
    """
    session_id: str | None = obj.get("id")
    if session_id:
        try:
            session = stripe.checkout.Session.retrieve(session_id, expand=["line_items"])
            items = list(session.line_items.data or [])
            if items:
                return [dict(item) for item in items]
        except stripe.StripeError:
            pass
    return list((obj.get("line_items") or {}).get("data") or [])


def _resolve_customer_id(obj: dict, experiment: str, stripe_customer: str | None) -> str:
    """
    Resolve internal customer_id in order of reliability:
    1. client_reference_id — set by programmatic checkout (guaranteed attribution)
    2. email lookup — matches payment-link buyer to an existing free-tier account
    3. auto-create — payment-link buyer with no prior account; creates paid record
    """
    client_ref = obj.get("client_reference_id")
    if client_ref:
        return client_ref

    email: str = (obj.get("customer_details") or {}).get("email") or ""
    if email:
        existing = lookup_customer_by_email(email)
        if existing:
            return existing

    if stripe_customer:
        return create_paid_customer(experiment, email, stripe_customer)

    return "unknown"


def _handle_checkout_completed(event: dict) -> None:
    obj = event["data"]["object"]
    if obj.get("payment_status") != "paid":
        return
    amount_total = obj.get("amount_total", 0) / 100.0
    if amount_total < 5.0:
        return

    line_items = _fetch_line_items(obj)
    experiment = None
    for item in line_items:
        price_id = (item.get("price") or {}).get("id")
        if price_id:
            experiment = price_to_experiment(price_id)
            if experiment:
                break
    if not experiment:
        experiment = obj.get("metadata", {}).get("experiment")
    if not experiment:
        return

    stripe_customer = obj.get("customer")
    customer_id = _resolve_customer_id(obj, experiment, stripe_customer)

    record_cre(
        experiment=experiment,
        customer_id=customer_id,
        amount_gbp=amount_total,
        stripe_event_id=event["id"],
        source="stripe_checkout",
    )
    if stripe_customer and customer_id != "unknown":
        upgrade_customer(stripe_customer, customer_id)


def _handle_invoice_paid(event: dict) -> None:
    obj = event["data"]["object"]
    amount_paid = obj.get("amount_paid", 0) / 100.0
    if amount_paid < 5.0:
        return
    lines = obj.get("lines", {}).get("data", [])
    experiment = None
    for line in lines:
        price_id = (line.get("price") or {}).get("id")
        if price_id:
            experiment = price_to_experiment(price_id)
            if experiment:
                break
    if not experiment:
        experiment = obj.get("metadata", {}).get("experiment")
    if not experiment:
        return
    customer_id = obj.get("customer") or "unknown"
    record_cre(
        experiment=experiment,
        customer_id=customer_id,
        amount_gbp=amount_paid,
        stripe_event_id=event["id"],
        source="stripe_invoice",
    )


def _handle_subscription_deleted(event: dict) -> None:
    obj = event["data"]["object"]
    stripe_customer = obj.get("customer")
    if stripe_customer:
        downgrade_customer(stripe_customer)


_HANDLERS = {
    "checkout.session.completed": _handle_checkout_completed,
    "invoice.paid": _handle_invoice_paid,
    "invoice.payment_succeeded": _handle_invoice_paid,
    "customer.subscription.deleted": _handle_subscription_deleted,
}
