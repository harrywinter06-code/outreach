"""
Z3 — per-business lander page + email/quiz capture.

Routes (mounted on the existing FastAPI dashboard):
- GET  /biz/{business_id}        — renders the lander HTML (genome + template-derived)
- POST /biz/{business_id}/lead   — captures email + quiz answers to business_leads

The lander pulls the business's genome from the DB + the fulfilment
template's required_inputs (so the quiz form has the right fields).

The lander is intentionally minimal HTML — no JS framework, no
analytics, no external assets. Goal is to validate the conversion
hypothesis, not to design a UI. If conversion proves viable, Z4 can
add A/B testing / styling polish.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

logger = logging.getLogger(__name__)

# Set by main.py at startup.
DB_POOL: Any | None = None


def get_router() -> APIRouter:
    """Build the FastAPI router for /biz endpoints."""
    router = APIRouter()

    @router.get("/biz/{business_id}", response_class=HTMLResponse)
    async def lander(business_id: str):
        biz = await _fetch_business(business_id)
        if biz is None:
            raise HTTPException(status_code=404, detail="business not found")
        if biz["status"] != "active":
            # Don't 404 — return a tombstone so old links don't dead-end ugly.
            return HTMLResponse(_render_tombstone(biz), status_code=410)
        return HTMLResponse(_render_lander(biz))

    @router.post("/biz/{business_id}/lead")
    async def lead(business_id: str, request: Request):
        biz = await _fetch_business(business_id)
        if biz is None or biz["status"] != "active":
            raise HTTPException(status_code=404, detail="business not found")
        form = await request.form()
        email = (form.get("email") or "").strip().lower()
        if "@" not in email or len(email) > 320:
            raise HTTPException(status_code=400, detail="valid email required")
        inputs: dict[str, str] = {}
        for key, value in form.multi_items():
            if key in ("email", "submit"):
                continue
            inputs[key] = str(value)[:2000]  # cap individual answers
        try:
            await _insert_lead(
                business_id=business_id, email=email, source="lander",
                metadata={"inputs": inputs},
            )
        except Exception as exc:
            logger.warning("lead insert failed for %s/%s: %s", business_id, email, exc)
            # Still redirect to payment — losing the lead row is recoverable
            # via the email captured by Stripe Checkout. Better to convert
            # than to error the customer out.
        payment_url = (biz.get("metadata") or {}).get("payment_link_url", "")
        if payment_url:
            return RedirectResponse(url=payment_url, status_code=303)
        return HTMLResponse(
            "<h1>Thanks — we'll be in touch.</h1>"
            "<p>(Payment link not yet configured for this business.)</p>",
            status_code=200,
        )

    return router


async def _fetch_business(business_id: str) -> dict | None:
    if DB_POOL is None:
        return None
    async with DB_POOL.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT business_id, name, niche, genome, status, metadata "
            "FROM businesses WHERE business_id = $1",
            business_id,
        )
    if row is None:
        return None
    out = dict(row)
    if isinstance(out.get("genome"), str):
        out["genome"] = json.loads(out["genome"])
    if isinstance(out.get("metadata"), str):
        out["metadata"] = json.loads(out["metadata"])
    return out


async def _insert_lead(
    *, business_id: str, email: str, source: str, metadata: dict,
) -> None:
    if DB_POOL is None:
        raise RuntimeError("DB_POOL not wired")
    async with DB_POOL.acquire() as conn:
        await conn.execute(
            "INSERT INTO business_leads (business_id, email, source, metadata) "
            "VALUES ($1, $2, $3, $4::jsonb) "
            "ON CONFLICT (business_id, email) DO UPDATE SET metadata = EXCLUDED.metadata",
            business_id, email, source, json.dumps(metadata),
        )


def _render_lander(biz: dict) -> str:
    genome = biz.get("genome") or {}
    niche = genome.get("niche_question", "Your question")
    price = float(genome.get("price_gbp", 3.0))
    template_name = genome.get("fulfilment_template", "")
    payment_link = (biz.get("metadata") or {}).get("payment_link_url", "")

    # Load template required_inputs so the form has the right fields.
    quiz_fields = []
    try:
        from clawbot.fulfilment import load_template
        tpl = load_template(template_name)
        quiz_fields = list(tpl.required_inputs)
    except Exception as exc:
        logger.warning("template load failed for lander %s: %s", biz["business_id"], exc)

    quiz_html = ""
    for field in quiz_fields:
        label = field.replace("_", " ").capitalize()
        quiz_html += (
            f'<label style="display:block;margin:12px 0 4px;font-weight:600;">{label}</label>'
            f'<textarea name="{field}" rows="2" '
            f'style="width:100%;padding:8px;border:1px solid #ccc;border-radius:4px;" required></textarea>'
        )

    payment_cta = ""
    if payment_link:
        payment_cta = (
            f'<p style="margin-top:24px;font-size:15px;color:#444;">'
            f'After submitting, you’ll be sent to secure Stripe checkout for the £{price:.2f} '
            f'personalised report. AI-generated. Full refund on request within 14 days.'
            f'</p>'
        )
    else:
        payment_cta = (
            '<p style="margin-top:24px;font-size:14px;color:#888;">'
            '(Payment surface not yet configured for this business — leave your '
            'email and we’ll reach out manually.)</p>'
        )

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_html_escape(niche)}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
       max-width: 640px; margin: 40px auto; padding: 0 20px; color: #222; line-height: 1.55; }}
h1 {{ font-size: 28px; line-height: 1.25; margin: 0 0 16px; }}
.tag {{ display: inline-block; background: #ffe9c4; color: #7a4a00;
       padding: 3px 8px; border-radius: 4px; font-size: 12px; font-weight: 600;
       letter-spacing: 0.04em; text-transform: uppercase; margin-bottom: 12px; }}
button {{ background: #1c6ea4; color: white; border: none; padding: 12px 24px;
         font-size: 16px; border-radius: 6px; cursor: pointer; margin-top: 16px; }}
</style></head><body>
<div class="tag">AI-generated personalised report &middot; £{price:.2f} &middot; UK</div>
<h1>{_html_escape(niche)}</h1>
<p>Answer the questions below and we'll generate a personalised report
based on your specific situation and HMRC public guidance. Sent to your
email within minutes of payment.</p>
<form method="POST" action="/biz/{biz['business_id']}/lead">
  {quiz_html}
  <label style="display:block;margin:18px 0 4px;font-weight:600;">Your email</label>
  <input type="email" name="email" required
    style="width:100%;padding:8px;border:1px solid #ccc;border-radius:4px;font-size:15px;">
  {payment_cta}
  <button type="submit">Continue to payment &rarr;</button>
</form>
<p style="margin-top:32px;font-size:12px;color:#888;">
This report is AI-generated based on your inputs and HMRC public guidance.
It is not legal or tax advice. Always consult a chartered accountant
before making decisions about your tax status. We refund any report on
request within 14 days &mdash; no questions.
</p>
</body></html>"""


def _render_tombstone(biz: dict) -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>No longer available</title></head><body style="font-family:sans-serif;max-width:540px;margin:60px auto;padding:0 20px;">
<h1>This page is no longer active.</h1>
<p>The business <code>{_html_escape(biz['name'])}</code> has been retired.</p>
</body></html>"""


def _html_escape(s: str) -> str:
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))
