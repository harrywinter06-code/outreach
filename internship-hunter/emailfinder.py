"""
Hunter.io email discovery.

Two strategies, in order of cost efficiency:
  1. domain_search — 1 credit per company domain. Returns the email pattern
     (e.g. {first}@company.com) and any publicly known addresses. Use this
     to construct emails for multiple contacts at the same company for free
     after the first lookup.
  2. email_finder — 1 credit per person. Returns a specific address with a
     confidence score. Fall back to this when domain_search gives no pattern.

Free tier: 25 searches/month. Starter ($34/mo): 500 searches.
"""

import requests
from config import HUNTER_API_KEY

BASE = "https://api.hunter.io/v2"


class HunterError(Exception):
    pass


class HunterCreditsExhausted(HunterError):
    pass


class HunterRateLimited(HunterError):
    pass


def _get(endpoint: str, params: dict) -> dict:
    if not HUNTER_API_KEY:
        raise HunterError("HUNTER_API_KEY not set in .env")
    params["api_key"] = HUNTER_API_KEY
    resp = requests.get(f"{BASE}/{endpoint}", params=params, timeout=10)
    if resp.status_code == 401:
        raise HunterError("Invalid Hunter.io API key")
    if resp.status_code == 402:
        raise HunterCreditsExhausted("Hunter.io monthly credits exhausted — upgrade at hunter.io/users/plan")
    if resp.status_code == 429:
        raise HunterRateLimited("Hunter.io rate limit reached — wait a minute and retry")
    resp.raise_for_status()
    return resp.json()


def get_domain_pattern(domain: str) -> dict:
    """
    Get the email pattern for a company domain.
    Returns dict with keys: pattern, emails (list), organization, credits_used.
    Pattern example: '{first}@domain.com' or '{first}.{last}@domain.com'
    1 credit per unique domain (free after first call if you cache results).
    """
    data = _get("domain-search", {"domain": domain, "limit": 25})
    d = data.get("data", {})
    pattern = d.get("pattern", "")
    emails_found = [
        {"email": e["value"], "first": e.get("first_name", ""), "last": e.get("last_name", ""), "confidence": e.get("confidence", 0)}
        for e in d.get("emails", [])
    ]
    return {
        "pattern": pattern,
        "emails": emails_found,
        "organization": d.get("organization", ""),
        "credits_used": data.get("meta", {}).get("credits_used", 1),
    }


def find_email(first_name: str, last_name: str, domain: str) -> dict:
    """
    Find a specific person's email address.
    Returns dict with keys: email, confidence, sources, credits_used.
    Confidence 0-100: >70 is reliable, 50-70 is plausible, <50 is a guess.
    1 credit per call.
    """
    data = _get("email-finder", {"first_name": first_name, "last_name": last_name, "domain": domain})
    d = data.get("data", {})
    return {
        "email": d.get("email", ""),
        "confidence": d.get("score", 0),
        "sources": [s.get("uri", "") for s in d.get("sources", [])[:3]],
        "credits_used": data.get("meta", {}).get("credits_used", 1),
    }


def construct_from_pattern(pattern: str, first_name: str, last_name: str, domain: str) -> str:
    """
    Construct an email from a domain pattern without using API credits.
    Pattern tokens: {first}, {last}, {f} (first initial), {l} (last initial)
    """
    if not pattern:
        return f"{first_name.lower()}@{domain}"
    email = (
        pattern
        .replace("{first}", first_name.lower())
        .replace("{last}", last_name.lower())
        .replace("{f}", first_name[0].lower() if first_name else "")
        .replace("{l}", last_name[0].lower() if last_name else "")
    )
    if "@" not in email:
        email = f"{email}@{domain}"
    return email


def get_account_info() -> dict:
    """Check remaining Hunter.io credits."""
    data = _get("account", {})
    acc = data.get("data", {})
    calls = acc.get("calls", {})
    return {
        "plan": acc.get("plan_name", "unknown"),
        "searches_used": calls.get("used", 0),
        "searches_available": calls.get("available", 0),
    }


def smart_find(first_name: str, last_name: str, domain: str, cached_pattern: str = "") -> dict:
    """
    Best-effort email lookup.
    1. If a cached pattern exists, construct without using credits.
    2. Otherwise call email_finder (1 credit).
    Returns dict: email, confidence, method, credits_used
    """
    if cached_pattern:
        email = construct_from_pattern(cached_pattern, first_name, last_name, domain)
        return {"email": email, "confidence": 75, "method": "pattern", "credits_used": 0}

    try:
        result = find_email(first_name, last_name, domain)
        result["method"] = "finder"
        return result
    except HunterRateLimited:
        import time
        time.sleep(65)
        try:
            result = find_email(first_name, last_name, domain)
            result["method"] = "finder"
            return result
        except HunterError:
            pass
    except HunterError:
        pass
    # Last resort: guess firstname@domain.com
    email = f"{first_name.lower()}@{domain}"
    return {"email": email, "confidence": 30, "method": "guess", "credits_used": 0}
