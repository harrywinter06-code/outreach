"""
Automated company research pipeline.

For each company:
  1. Hunter.io domain search — gets domain pattern + any known people with titles
  2. Scrape company homepage — raw text for context
  3. Claude Sonnet — picks the best contact from people list, writes 2-3 sentence context
  4. Email finder — looks up the specific person's address

Outputs a ResearchResult that can be handed directly to generate.py + queue_email().

Success rate:
  - Hunter has people data: ~55% of companies → fully automatic
  - Hunter has domain/pattern only: ~25% → contact name needed manually
  - Hunter has nothing: ~20% → domain + context auto-filled, contact manual
"""

import time
import requests
from urllib.parse import urlparse
from anthropic import Anthropic
from anthropic.types import TextBlock
from dataclasses import dataclass
from config import ANTHROPIC_API_KEY, GENERATE_MODEL
from emailfinder import get_domain_pattern, smart_find, HunterError, HunterCreditsExhausted, construct_from_pattern
from tracker import get_cached_pattern, cache_domain_pattern

# Title relevance score — higher = better contact for Harry's internship ask
TITLE_SCORES = {
    "founder": 10, "co-founder": 10, "cofounder": 10,
    "cto": 9, "chief technology": 9,
    "vp engineering": 8, "vp of engineering": 8, "head of engineering": 8,
    "head of data": 8, "vp data": 8, "vp of data": 8,
    "head of machine learning": 8, "head of ml": 8, "head of ai": 8,
    "director of engineering": 7, "director of data": 7, "director of ml": 7,
    "data lead": 6, "ml lead": 6, "engineering lead": 6,
    "ceo": 5, "chief executive": 5,  # busy but occasionally responsive
    "chief product": 4, "cpo": 4,
    "product lead": 3,
}


def _title_score(title: str) -> int:
    t = title.lower()
    for keyword, score in TITLE_SCORES.items():
        if keyword in t:
            return score
    return 1


@dataclass
class ResearchResult:
    company: str
    domain: str
    contact_first: str = ""
    contact_last: str = ""
    contact_title: str = ""
    contact_email: str = ""
    email_confidence: int = 0
    email_method: str = ""
    context: str = ""
    success: str = "partial"   # "full" | "partial" | "failed"
    notes: str = ""


def _scrape_homepage(domain: str, timeout: int = 15) -> str:
    """Fetch rendered homepage text via Jina Reader. Handles React/Next.js SPAs."""
    for scheme in ("https", "http"):
        try:
            resp = requests.get(
                f"https://r.jina.ai/{scheme}://{domain}",
                timeout=timeout,
                headers={"Accept": "text/plain", "X-No-Cache": "true"},
            )
            if resp.status_code == 200 and resp.text.strip():
                return resp.text[:3000]
        except requests.RequestException:
            continue
    return ""


def _claude_synthesize(
    company: str,
    sector: str,
    notes: str,
    people: list[dict],
    web_text: str,
    has_ucl_alumni: bool = False,
) -> dict:
    """
    Single Claude call: pick best contact + write 2-3 sentence context.
    Returns {contact_first, contact_last, contact_title, context}
    """
    client = Anthropic(api_key=ANTHROPIC_API_KEY)

    people_block = ""
    if people:
        lines = [f"  - {p.get('first','?')} {p.get('last','?')} | {p.get('position','?')} | email_confidence: {p.get('confidence',0)}" for p in people[:10]]
        people_block = "People found at this company:\n" + "\n".join(lines)
    else:
        people_block = "No people found in Hunter.io database for this company."

    ucl_note = (
        "\nUCL ALUMNI CONTEXT: A UCL alumnus works at this company. "
        "The generated CONTEXT should naturally reference this shared connection — "
        "e.g. 'I noticed [Name] from UCL works on your [team]' — as the warm opener instead of a generic company observation."
    ) if has_ucl_alumni else ""

    prompt = f"""You are researching a company for a cold email from Harry Winter (UCL undergraduate, seeking a summer 2026 data/analyst/AI internship).

Company: {company}
Sector: {sector}
Notes: {notes}{ucl_note}

{people_block}

Company website text (may be incomplete):
{web_text[:2000] if web_text else 'Could not scrape website.'}

Task 1 — Pick the best contact:
Choose the single best person for Harry to cold email about a summer internship. Prefer founders and technical leads over HR. If no people are listed, output empty strings.

Task 2 — Write company context:
Write exactly 2-3 sentences that Harry can use as the personalised opener in a cold email. Must be specific to THIS company — what they actually do, something interesting about their product/team/recent work. No generic phrases like "innovative company" or "exciting mission". Harry will use these sentences to demonstrate he did his research.

Respond in this exact format (nothing else):
FIRST: [first name or UNKNOWN]
LAST: [last name or UNKNOWN]
TITLE: [their title or UNKNOWN]
CONTEXT: [2-3 sentences of specific company context]"""

    response = client.messages.create(
        model=GENERATE_MODEL,
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )
    text = next((b.text for b in response.content if isinstance(b, TextBlock)), "")

    result = {"contact_first": "", "contact_last": "", "contact_title": "", "context": ""}
    for line in text.strip().split("\n"):
        if line.startswith("FIRST:"):
            val = line[6:].strip()
            result["contact_first"] = "" if val == "UNKNOWN" else val
        elif line.startswith("LAST:"):
            val = line[5:].strip()
            result["contact_last"] = "" if val == "UNKNOWN" else val
        elif line.startswith("TITLE:"):
            val = line[6:].strip()
            result["contact_title"] = "" if val == "UNKNOWN" else val
        elif line.startswith("CONTEXT:"):
            result["context"] = line[8:].strip()
    return result


def research_company(
    name: str,
    domain: str,
    sector: str = "",
    notes: str = "",
    has_ucl_alumni: bool = False,
) -> ResearchResult:
    """
    Full research pipeline for a single company.
    Returns ResearchResult — always returns something, never raises.
    """
    result = ResearchResult(company=name, domain=domain)

    # 1. Hunter domain search
    people = []
    raw_people = []
    pattern = get_cached_pattern(domain)
    try:
        hunter_data = get_domain_pattern(domain)
        if hunter_data["pattern"] and not pattern:
            cache_domain_pattern(domain, hunter_data["pattern"])
            pattern = hunter_data["pattern"]
        # Sort people by title relevance
        raw_people = hunter_data.get("emails", [])
        people = sorted(raw_people, key=lambda p: _title_score(p.get("position", "")), reverse=True)
    except HunterCreditsExhausted:
        raise
    except HunterError as e:
        result.notes = f"Hunter error: {e}"
    except Exception as e:
        result.notes = f"Hunter unexpected: {e}"

    # 2. Scrape homepage
    web_text = _scrape_homepage(domain)

    # 3. Claude synthesis
    try:
        synthesis = _claude_synthesize(name, sector, notes, people, web_text, has_ucl_alumni=has_ucl_alumni)
        result.contact_first = synthesis["contact_first"]
        result.contact_last  = synthesis["contact_last"]
        result.contact_title = synthesis["contact_title"]
        result.context       = synthesis["context"]
    except Exception as e:
        result.notes += f" | Claude error: {e}"
        # Fall back: pick best person from Hunter list without Claude
        if people:
            best = people[0]
            result.contact_first = best.get("first", "")
            result.contact_last  = best.get("last", "")
            result.contact_title = best.get("position", "")

    # 4. Email lookup — check Hunter's returned list first (free), then fall back to API call
    if result.contact_first and result.contact_last:
        first_lower = result.contact_first.lower()
        last_lower  = result.contact_last.lower()
        hunter_hit  = next(
            (p for p in raw_people
             if p.get("first", "").lower() == first_lower and p.get("last", "").lower() == last_lower),
            None,
        )
        if hunter_hit and hunter_hit.get("email"):
            result.contact_email    = hunter_hit["email"]
            result.email_confidence = hunter_hit.get("confidence", 70)
            result.email_method     = "hunter_list"
        else:
            try:
                email_result = smart_find(result.contact_first, result.contact_last, domain, pattern)
                result.contact_email     = email_result["email"]
                result.email_confidence  = email_result["confidence"]
                result.email_method      = email_result["method"]
            except Exception as e:
                if pattern:
                    result.contact_email    = construct_from_pattern(pattern, result.contact_first, result.contact_last, domain)
                    result.email_confidence = 40
                    result.email_method     = "pattern_fallback"
                result.notes += f" | Email lookup error: {e}"

    # Assess success level
    has_contact = bool(result.contact_first and result.contact_last)
    has_email   = bool(result.contact_email)
    has_context = bool(result.context)

    if has_contact and has_email and has_context:
        result.success = "full"
    elif has_context or has_contact:
        result.success = "partial"
    else:
        result.success = "failed"

    return result


def research_batch(
    companies: list[dict],
    on_progress=None,
    delay: float = 1.5,
) -> tuple[list[ResearchResult], bool]:
    """
    Research a list of companies.
    companies: list of dicts with keys: name, website (domain), sector, notes
    on_progress(i, total, name, result): called after each company
    delay: seconds between companies (be polite to Hunter.io)
    Returns (results, credits_exhausted) — credits_exhausted=True means Hunter
    quota was hit mid-batch and remaining companies were not researched.
    """
    results = []
    credits_exhausted = False

    for i, co in enumerate(companies):
        raw = co.get("website", "")
        if raw and "://" not in raw:
            raw = "https://" + raw
        domain = urlparse(raw).netloc if raw else ""
        if not domain:
            domain = co.get("name", "").lower().replace(" ", "") + ".com"

        try:
            r = research_company(
                name=co.get("name", ""),
                domain=domain,
                sector=co.get("sector", ""),
                notes=co.get("notes", ""),
                has_ucl_alumni=bool(co.get("has_ucl_alumni", False)),
            )
        except HunterCreditsExhausted:
            credits_exhausted = True
            r = ResearchResult(
                company=co.get("name", ""),
                domain=domain,
                success="failed",
                notes="Hunter.io credits exhausted — upgrade at hunter.io/users/plan",
            )
            results.append(r)
            if on_progress:
                on_progress(i + 1, len(companies), co.get("name", ""), r)
            break

        results.append(r)

        if on_progress:
            on_progress(i + 1, len(companies), co.get("name", ""), r)

        if i < len(companies) - 1:
            time.sleep(delay)

    return results, credits_exhausted
