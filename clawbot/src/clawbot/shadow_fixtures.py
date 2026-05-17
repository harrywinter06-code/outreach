"""Realistic API response fixtures for shadow-mode skill validation.

These are NOT contract tests against live APIs — they are best-effort
representations based on the official documented response shape. Skills that
hallucinate a different shape (e.g., `r["data"]["id"]` where the real API
returns `r["id"]`) will fail shadow validation against these fixtures.

When an API changes its shape, update the fixture; until then, skills built
to the old shape continue to pass shadow. That mismatch is acceptable — the
canary mode (Task 40) catches it on the first live call.
"""
from __future__ import annotations

import re
from typing import Any

# (method_upper, url_regex, response_dict)
FIXTURES: list[tuple[str, re.Pattern[str], dict[str, Any]]] = [
    # ---- Stripe ----
    ("POST", re.compile(r"^https://api\.stripe\.com/v1/products$"), {
        "status": 200, "headers": {"content-type": "application/json"},
        "json": {
            "id": "prod_FIXTURE", "object": "product", "active": True,
            "name": "FIXTURE", "description": "FIXTURE",
            "created": 0, "metadata": {},
        },
    }),
    ("POST", re.compile(r"^https://api\.stripe\.com/v1/prices$"), {
        "status": 200, "headers": {},
        "json": {
            "id": "price_FIXTURE", "object": "price", "active": True,
            "currency": "gbp", "unit_amount": 900, "product": "prod_FIXTURE",
        },
    }),
    ("POST", re.compile(r"^https://api\.stripe\.com/v1/payment_links$"), {
        "status": 200, "headers": {},
        "json": {
            "id": "plink_FIXTURE", "object": "payment_link",
            "url": "https://buy.stripe.com/FIXTURE", "active": True,
        },
    }),
    ("GET", re.compile(r"^https://api\.stripe\.com/v1/charges"), {
        "status": 200, "headers": {},
        "json": {"object": "list", "data": [], "has_more": False},
    }),

    # ---- X (Twitter) v2 — uses {"data": {...}} wrapper ----
    ("POST", re.compile(r"^https://api\.twitter\.com/2/tweets$"), {
        "status": 201, "headers": {},
        "json": {"data": {"id": "1234567890", "text": "FIXTURE"}},
    }),

    # ---- LinkedIn UGC ----
    ("POST", re.compile(r"^https://api\.linkedin\.com/v2/ugcPosts$"), {
        "status": 201, "headers": {"x-restli-id": "urn:li:share:FIXTURE"},
        "json": {},
    }),
    ("GET", re.compile(r"^https://api\.linkedin\.com/v2/me$"), {
        "status": 200, "headers": {},
        "json": {"id": "abc12345", "localizedFirstName": "F", "localizedLastName": "L"},
    }),

    # ---- Reddit ----
    ("POST", re.compile(r"^https://www\.reddit\.com/api/v1/access_token$"), {
        "status": 200, "headers": {},
        "json": {"access_token": "FIXTURE_TOKEN", "token_type": "bearer",
                 "expires_in": 86400, "scope": "*"},
    }),
    ("POST", re.compile(r"^https://oauth\.reddit\.com/api/submit$"), {
        "status": 200, "headers": {},
        "json": {"json": {"data": {"id": "abc123",
                                   "url": "https://reddit.com/r/x/comments/abc123"}}},
    }),

    # ---- Resend (email) ----
    ("POST", re.compile(r"^https://api\.resend\.com/emails$"), {
        "status": 200, "headers": {},
        "json": {"id": "re_FIXTURE_id"},
    }),

    # ---- Gumroad ----
    ("GET", re.compile(r"^https://api\.gumroad\.com/v2/products"), {
        "status": 200, "headers": {},
        "json": {"success": True, "products": []},
    }),
    ("GET", re.compile(r"^https://api\.gumroad\.com/v2/sales"), {
        "status": 200, "headers": {},
        "json": {"success": True, "sales": [], "next_page_url": None},
    }),

    # ---- GitHub ----
    ("POST", re.compile(r"^https://api\.github\.com/repos/[^/]+/[^/]+/issues$"), {
        "status": 201, "headers": {},
        "json": {"number": 42, "html_url": "https://github.com/x/y/issues/42",
                 "title": "FIXTURE", "state": "open"},
    }),
    ("POST", re.compile(r"^https://api\.github\.com/repos/[^/]+/[^/]+/pulls$"), {
        "status": 201, "headers": {},
        "json": {"number": 7, "html_url": "https://github.com/x/y/pull/7", "state": "open"},
    }),
    ("POST", re.compile(r"^https://api\.github\.com/user/repos$"), {
        "status": 201, "headers": {},
        "json": {"id": 999, "name": "FIXTURE", "html_url": "https://github.com/u/FIXTURE",
                 "clone_url": "https://github.com/u/FIXTURE.git"},
    }),

    # ---- Hunter.io ----
    ("GET", re.compile(r"^https://api\.hunter\.io/v2/email-finder"), {
        "status": 200, "headers": {},
        "json": {"data": {"email": "fixture@example.com", "score": 80}},
    }),

    # ---- Apollo ----
    ("POST", re.compile(r"^https://api\.apollo\.io/v1/people/search$"), {
        "status": 200, "headers": {},
        "json": {"people": [], "pagination": {"page": 1, "total_entries": 0}},
    }),

    # ---- Companies House ----
    ("GET", re.compile(r"^https://api\.company-information\.service\.gov\.uk/search"), {
        "status": 200, "headers": {},
        "json": {"total_results": 0, "items": []},
    }),

    # ---- Cloudflare ----
    ("POST", re.compile(r"^https://api\.cloudflare\.com/client/v4/zones/[^/]+/dns_records$"), {
        "status": 200, "headers": {},
        "json": {"success": True, "result": {"id": "cf_FIXTURE", "name": "x", "type": "A"}},
    }),
]


def lookup_fixture(method: str, url: str) -> dict[str, Any] | None:
    """Return the fixture for a (method, url) pair, or None if unmatched."""
    method_upper = method.upper()
    for m, pat, fixture in FIXTURES:
        if m == method_upper and pat.search(url):
            return fixture
    return None
