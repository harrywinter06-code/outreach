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

# Set by main.py at startup. The webhook reads them at request time so
# this module can be imported before the components exist.
BUSINESS_STORE: Any | None = None
LLM_POOL: Any | None = None      # Z3: needed for fulfilment skill LLM calls
BUS: Any | None = None
BRAIN: Any | None = None


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
        # Z3: self-pay filter. If billing email matches OPERATOR_EMAIL,
        # tag this as is_self_paid=True so fitness excludes it. Prevents
        # operator's own test purchases from inflating the £ signal.
        customer_email = _extract_customer_email(obj)
        is_self = _is_operator_email(customer_email)
        inserted = await BUSINESS_STORE.record_revenue(
            business_id=biz_id,
            amount_gbp=amount_gbp,
            source="stripe",
            external_id=str(obj.get("id") or event.get("id")),
            is_self_paid=is_self,
            metadata={
                "stripe_event_id": event.get("id"),
                "stripe_event_type": event_type,
                "customer_email": customer_email,
            },
        )
        logger.info(
            "Stripe webhook → business_revenue: biz=%s amount=£%.2f self_paid=%s inserted=%s",
            biz_id, amount_gbp, is_self, inserted,
        )
        # Z3 fulfilment: only fire delivery on the FIRST insert (avoids
        # double-emails on Stripe webhook retries) AND skip self-paid
        # (test charges don't need real fulfilment).
        if inserted and not is_self and customer_email:
            await _fire_fulfilment(
                business_id=biz_id, customer_email=customer_email,
                charge_id=str(obj.get("id") or event.get("id")),
            )
        return {"ok": True, "routed": True, "inserted": inserted, "self_paid": is_self}

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


def _extract_customer_email(charge_or_pi: dict) -> str:
    """Pull the customer email from a Stripe charge or payment_intent.
    Returns lowercased email or empty string."""
    billing = (charge_or_pi.get("billing_details") or {})
    email = billing.get("email") or charge_or_pi.get("receipt_email") or ""
    return str(email).strip().lower()


def _is_operator_email(email: str) -> bool:
    """True if this email matches the operator (test purchases shouldn't
    inflate fitness). The OPERATOR_EMAIL env var overrides the default."""
    if not email:
        return False
    import os
    operator = os.environ.get("OPERATOR_EMAIL", "harrywinter06@gmail.com").strip().lower()
    return email == operator


async def _fire_fulfilment(
    *, business_id: str, customer_email: str, charge_id: str,
) -> None:
    """Generate + email the personalised report after a confirmed payment.

    Fulfilment is a platform-owned side-effect of a confirmed charge, not
    an agent-callable skill. Pulls business genome → loads fulfilment
    template → renders with lead's captured inputs → calls LLM → sends
    email. Errors logged but not raised — webhook must still return 200
    to Stripe (we'll fix delivery via operator manual replay if needed)."""
    if BUSINESS_STORE is None or not hasattr(BUSINESS_STORE, "_pool"):
        logger.error("BUSINESS_STORE missing or unpooled — cannot fire fulfilment")
        return
    if LLM_POOL is None:
        logger.error("LLM_POOL not wired into stripe_webhook — cannot fire fulfilment")
        return
    pool = BUSINESS_STORE._pool

    try:
        # 1. Genome lookup
        async with pool.acquire() as conn:
            biz_row = await conn.fetchrow(
                "SELECT genome FROM businesses WHERE business_id = $1",
                business_id,
            )
        if biz_row is None:
            logger.warning("Fulfilment: business %s not found, skipping", business_id)
            return
        genome = biz_row["genome"]
        if isinstance(genome, str):
            genome = json.loads(genome)
        template_name = genome.get("fulfilment_template", "")
        niche = genome.get("niche_question", "your query")

        # 2. Lead inputs lookup
        async with pool.acquire() as conn:
            lead_row = await conn.fetchrow(
                "SELECT metadata FROM business_leads "
                "WHERE business_id = $1 AND email = $2 "
                "ORDER BY captured_at DESC LIMIT 1",
                business_id, customer_email,
            )
        inputs: dict = {}
        if lead_row is not None:
            md = lead_row["metadata"]
            if isinstance(md, str):
                md = json.loads(md)
            if isinstance(md, dict):
                inputs = md.get("inputs", {}) or {}

        # 3. Load + render fulfilment template
        from clawbot.fulfilment import load_template, FulfilmentTemplateError
        try:
            tpl = load_template(template_name)
        except FulfilmentTemplateError as exc:
            logger.error("Fulfilment template load failed for %s: %s", business_id, exc)
            return
        try:
            prompt = tpl.render_prompt(inputs)
        except FulfilmentTemplateError as exc:
            logger.warning(
                "Fulfilment template missing inputs for %s (rendering with placeholders): %s",
                business_id, exc,
            )
            filled = {**inputs, **{k: "(not provided)" for k in tpl.required_inputs}}
            prompt = tpl.render_prompt(filled)

        # 4. Generate report via LLM
        messages = [
            {"role": "system",
             "content": "You are an expert UK contractor accountant. Produce the personalised report exactly as the prompt specifies. Markdown formatting."},
            {"role": "user", "content": prompt},
        ]
        report = await LLM_POOL.complete(messages, tier="executive", max_tokens=2000)

        # 5. Email the customer. Subject discloses AI generation per charter.
        subject = f"Your AI-generated {niche[:80]} report (charge {charge_id[:16]})"
        body = (
            "Hi,\n\n"
            f"Your personalised {niche} report is below.\n"
            f"Reference: {charge_id}\n\n"
            "--- AI DISCLOSURE ---\n"
            f"{tpl.ai_disclosure}\n\n"
            "--- REPORT ---\n\n"
            f"{report}\n\n"
            "---\n"
            "Questions or refund: reply to this email.\n"
        )
        # Email send: direct Resend call if configured, else log + skip.
        # Avoid building a full SkillCtx since fulfilment is platform code.
        from clawbot.config import settings
        if settings.resend_api_key and getattr(settings, "email_domain", ""):
            import httpx
            from_addr = f"reports@{settings.email_domain}"
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    "https://api.resend.com/emails",
                    headers={
                        "Authorization": f"Bearer {settings.resend_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "from": from_addr,
                        "to": [customer_email],
                        "subject": subject,
                        "text": body,
                    },
                )
                if resp.status_code >= 400:
                    logger.error(
                        "Resend send failed (%s) for biz=%s: %s",
                        resp.status_code, business_id, resp.text[:300],
                    )
                else:
                    logger.info(
                        "Fulfilment email delivered: biz=%s to=%s",
                        business_id, customer_email,
                    )
        else:
            logger.warning(
                "RESEND_API_KEY or EMAIL_DOMAIN unset — fulfilment for biz=%s logged "
                "to disk but NOT emailed. Operator must replay manually.",
                business_id,
            )
            # Persist the unsent report so operator can copy-paste-send
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE businesses SET metadata = metadata || $2::jsonb "
                    "WHERE business_id = $1",
                    business_id,
                    json.dumps({
                        f"unsent_fulfilment_{charge_id[:14]}": {
                            "to": customer_email,
                            "subject": subject,
                            "body": body[:8000],
                        }
                    }),
                )
    except Exception as exc:
        logger.error(
            "Fulfilment fire-and-forget exception for biz=%s: %s",
            business_id, exc, exc_info=True,
        )


def get_router():
    """Public accessor — called by dashboard create_app to mount the route."""
    return _build_router()
