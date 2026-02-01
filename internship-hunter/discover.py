"""
Job discovery from ATS boards and curated APIs.

Sources:
  1. Remotive        — free public API, remote-first jobs
  2. Greenhouse ATS  — public board API, 32 UK/global slugs
  3. Lever ATS       — public postings API, 7 UK/global slugs
  4. Reed.co.uk      — UK's largest job board (free API key required)
  5. Funding leads   — Sifted / UKTN / TechCrunch UK RSS → newly funded
                       companies added to the Companies table for cold outreach

Slug management:
  - Confirmed slugs have been validated live
  - Candidate slugs may be dead — run `python discover.py validate` to check
  - Dead slugs are cached in the DB and auto-skipped on future runs
"""

import re
import json
import time
import logging
import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from curl_cffi import requests as cffi_requests
from rich.console import Console
from anthropic import Anthropic
from anthropic.types import TextBlock
from config import TARGET_KEYWORDS, TARGET_LOCATIONS, EXCLUDE_KEYWORDS, REED_API_KEY, ANTHROPIC_API_KEY, EXTRACT_MODEL, ACCEPT_LOCATION_UNKNOWN
from tracker import insert_job, get_conn, upsert_company

console = Console()
log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}


# ── Relevance filters ─────────────────────────────────────────────────────────

def _is_relevant(title: str, description: str = "") -> bool:
    text = (title + " " + description).lower()
    if any(kw.lower() in text for kw in EXCLUDE_KEYWORDS):
        return False
    return any(kw.lower() in text for kw in TARGET_KEYWORDS)


def _is_target_location(location: str) -> bool:
    if not location:
        return ACCEPT_LOCATION_UNKNOWN
    return any(t in location.lower() for t in TARGET_LOCATIONS)


# ── Slug validation cache ─────────────────────────────────────────────────────

def _ensure_slug_table():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ats_slugs (
                platform TEXT NOT NULL,
                slug     TEXT NOT NULL,
                valid    INTEGER DEFAULT 1,
                checked  TEXT,
                PRIMARY KEY (platform, slug)
            )
        """)


def _mark_slug(platform: str, slug: str, valid: bool):
    _ensure_slug_table()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO ats_slugs (platform, slug, valid, checked)
               VALUES (?,?,?,datetime('now'))
               ON CONFLICT(platform, slug) DO UPDATE
               SET valid=excluded.valid, checked=excluded.checked""",
            (platform, slug, 1 if valid else 0)
        )


def _slug_is_known_dead(platform: str, slug: str) -> bool:
    _ensure_slug_table()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT valid FROM ats_slugs WHERE platform=? AND slug=?", (platform, slug)
        ).fetchone()
        return row is not None and row["valid"] == 0


# ── Remotive API ──────────────────────────────────────────────────────────────

def fetch_remotive(categories=("data", "software-dev"), search="intern") -> list[dict]:
    """Remotive public JSON API — reliable, no auth required."""
    jobs = []
    for cat in categories:
        url = f"https://remotive.com/api/remote-jobs?category={cat}&search={search}&limit=50"
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json().get("jobs", [])
            found = 0
            for job in data:
                title = job.get("title", "")
                description = BeautifulSoup(job.get("description", ""), "lxml").get_text()[:2000]
                if _is_relevant(title, description):
                    jobs.append({
                        "title": title,
                        "company": job.get("company_name", ""),
                        "location": job.get("candidate_required_location", "Worldwide"),
                        "url": job.get("url", ""),
                        "source": "Remotive",
                        "description": description,
                        "salary": job.get("salary", ""),
                    })
                    found += 1
            console.print(f"  Remotive [{cat}]: {found} relevant of {len(data)} total")
            time.sleep(1)
        except requests.RequestException as e:
            console.print(f"  [red]FAIL Remotive [{cat}]: {e}[/red]")
        except Exception as e:
            console.print(f"  [red]ERROR Remotive [{cat}]: {e}[/red]")
    return jobs


# ── Reed.co.uk API ────────────────────────────────────────────────────────────
# Free API key at: https://www.reed.co.uk/developers/jobseeker
# Auth: HTTP Basic with API key as username, blank password.
# Free tier: generous daily limit, plenty for daily discovery runs.

REED_SEARCHES = [
    "data intern",
    "analyst intern",
    "machine learning intern",
    "quantitative intern",
]


def fetch_reed_jobs() -> list[dict]:
    """
    Reed.co.uk — UK's largest job board. London-focused search.
    Set REED_API_KEY in .env (free at reed.co.uk/developers).
    """
    if not REED_API_KEY:
        console.print(
            "  [yellow]Reed: REED_API_KEY not set — skipping. "
            "Register free at reed.co.uk/developers[/yellow]"
        )
        return []

    jobs: list[dict] = []
    seen_ids: set[int] = set()

    for keywords in REED_SEARCHES:
        try:
            resp = requests.get(
                "https://www.reed.co.uk/api/1.0/search",
                auth=(REED_API_KEY, ""),
                params={
                    "keywords": keywords,
                    "location": "London",
                    "distancefromlocation": 20,
                    "resultsToTake": 100,
                },
                timeout=15,
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
            found = 0
            for job in results:
                job_id = job.get("jobId", 0)
                if job_id in seen_ids:
                    continue
                seen_ids.add(job_id)
                title = job.get("jobTitle", "")
                description = job.get("jobDescription", "") or ""
                if not _is_relevant(title, description):
                    continue
                min_sal = job.get("minimumSalary")
                max_sal = job.get("maximumSalary")
                salary = f"£{int(min_sal):,}–£{int(max_sal):,}" if min_sal else ""
                jobs.append({
                    "title": title,
                    "company": job.get("employerName", ""),
                    "location": job.get("locationName", "London"),
                    "url": f"https://www.reed.co.uk/jobs/{job_id}",
                    "source": "Reed",
                    "description": description[:2000],
                    "salary": salary,
                })
                found += 1
            console.print(f"  Reed [{keywords!r}]: {found} relevant of {len(results)}")
            time.sleep(0.5)
        except requests.RequestException as e:
            console.print(f"  [red]FAIL Reed [{keywords!r}]: {e}[/red]")
        except Exception as e:
            console.print(f"  [red]ERROR Reed [{keywords!r}]: {e}[/red]")

    return jobs


# ── Greenhouse ATS ────────────────────────────────────────────────────────────

_SLUG_NAME_OVERRIDES = {
    "modulrfinance":  "Modulr Finance",
    "benevolentai":   "BenevolentAI",
    "polyai":         "PolyAI",
    "signal-ai":      "Signal AI",
    "gocardless":     "GoCardless",
    "starlingbank":   "Starling Bank",
    "ada-support":    "Ada",
    "benchsci":       "BenchSci",
    "thoughtmachine": "Thought Machine",
}


def _slug_to_name(slug: str) -> str:
    return _SLUG_NAME_OVERRIDES.get(slug, slug.replace("-", " ").title())


GREENHOUSE_SLUGS = [
    # ── Confirmed live (validated 2026-05-09) ─────────────────────────────────
    "monzo", "modulrfinance", "form3", "wayve",
    "anthropic", "deepmind", "stripe", "figma", "brex",
    # ── UK fintech / payments ─────────────────────────────────────────────────
    "gocardless", "checkout", "starlingbank", "marshmallow",
    "featurespace", "quantexa", "onfido", "freetrade",
    "primer", "hyperexponential", "cleo", "multiverse",
    "attest", "tractable",
    # ── UK AI / ML ─────────────────────────────────────────────────────────────
    "polyai", "benevolentai", "luminance", "synthesized",
    "cytora", "greyparrot", "signal-ai",
    # ── Global tech with London presence ──────────────────────────────────────
    "coinbase", "notion", "datadog",
    # ── Canada — IEC working holiday, no company sponsorship needed ────────────
    "cohere", "ada-support", "benchsci", "wealthsimple", "clearco",
    # ── EU — portal-only targets, worth monitoring for roles ──────────────────
    "dataiku", "personio", "sumup",
]


def fetch_greenhouse_board(slug: str) -> tuple[list[dict], str]:
    """Returns (jobs, status) — status: 'ok' | 'dead' | 'error:<code>'"""
    if _slug_is_known_dead("greenhouse", slug):
        return [], "dead"
    try:
        url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
        resp = requests.get(url, timeout=10)
        if resp.status_code == 404:
            _mark_slug("greenhouse", slug, valid=False)
            return [], "dead"
        if resp.status_code != 200:
            return [], f"error:{resp.status_code}"
        data = resp.json().get("jobs", [])
        _mark_slug("greenhouse", slug, valid=True)
        jobs = []
        for job in data:
            title = job.get("title", "")
            location = job.get("location", {}).get("name", "")
            description = BeautifulSoup(job.get("content", ""), "lxml").get_text()[:2000]
            if _is_relevant(title, description) and _is_target_location(location):
                jobs.append({
                    "title": title,
                    "company": _slug_to_name(slug),
                    "location": location,
                    "url": job.get("absolute_url", ""),
                    "source": "Greenhouse",
                    "description": description,
                    "salary": "",
                })
        return jobs, "ok"
    except requests.RequestException as e:
        return [], f"error:{e}"


# ── Lever ATS ─────────────────────────────────────────────────────────────────

LEVER_SLUGS = [
    # ── Confirmed live ────────────────────────────────────────────────────────
    "palantir",
    # ── Candidates (run `python discover.py validate` to confirm) ─────────────
    "improbable",
    "thoughtmachine",
    "wise",
    "zego",
    "curve",
    "oxbotica",
]


def fetch_lever_board(slug: str) -> tuple[list[dict], str]:
    """Returns (jobs, status) — status: 'ok' | 'dead' | 'error:<code>'"""
    if _slug_is_known_dead("lever", slug):
        return [], "dead"
    try:
        url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
        resp = requests.get(url, timeout=10)
        if resp.status_code == 404:
            _mark_slug("lever", slug, valid=False)
            return [], "dead"
        if resp.status_code != 200:
            return [], f"error:{resp.status_code}"
        data = resp.json()
        if not isinstance(data, list):
            _mark_slug("lever", slug, valid=False)
            return [], "dead"
        _mark_slug("lever", slug, valid=True)
        jobs = []
        for job in data:
            title = job.get("text", "")
            location = job.get("categories", {}).get("location", "")
            description = BeautifulSoup(job.get("descriptionPlain", ""), "lxml").get_text()[:2000]
            if _is_relevant(title, description) and _is_target_location(location):
                jobs.append({
                    "title": title,
                    "company": _slug_to_name(slug),
                    "location": location,
                    "url": job.get("hostedUrl", ""),
                    "source": "Lever",
                    "description": description,
                    "salary": "",
                })
        return jobs, "ok"
    except requests.RequestException as e:
        return [], f"error:{e}"


def fetch_all_ats() -> list[dict]:
    all_jobs: list[dict] = []
    dead, errors, ok = 0, 0, 0

    for slug in GREENHOUSE_SLUGS:
        jobs, status = fetch_greenhouse_board(slug)
        if status == "ok":
            ok += 1
            if jobs:
                console.print(f"  [green]Greenhouse/{slug}: {len(jobs)} relevant[/green]")
        elif status == "dead":
            dead += 1
        else:
            errors += 1
            console.print(f"  [red]Greenhouse/{slug}: {status}[/red]")
        all_jobs.extend(jobs)
        time.sleep(0.4)

    for slug in LEVER_SLUGS:
        jobs, status = fetch_lever_board(slug)
        if status == "ok":
            ok += 1
            if jobs:
                console.print(f"  [green]Lever/{slug}: {len(jobs)} relevant[/green]")
        elif status == "dead":
            dead += 1
        else:
            errors += 1
            console.print(f"  [red]Lever/{slug}: {status}[/red]")
        all_jobs.extend(jobs)
        time.sleep(0.4)

    console.print(f"  ATS: {ok} boards responded · {dead} dead/skipped · {errors} errors")
    return all_jobs


# ── Funding leads (RSS) ───────────────────────────────────────────────────────
# Freshly funded companies are the best cold email targets:
#   — cash-rich and actively hiring
#   — founders still read their own inbox
#   — no formal intern process yet = you can create the role
#
# Pipeline: RSS feeds → keyword pre-filter → Claude Haiku batch extraction →
#           structured leads (company, sector, HQ, round, amount, hook).
# Catches active and passive voice headlines, varied phrasing, and provides
# sector/size signals that pure regex cannot.

_FUNDING_KEYWORDS = {
    "£", "$", "€", "fund", "raise", "invest", "series", "seed",
    "round", "million", "secures", "capital", "backed", "closes", "growth",
}


def _looks_like_funding_news(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in _FUNDING_KEYWORDS)


def _extract_leads_with_claude(articles: list[dict]) -> list[dict]:
    """
    articles: list of {source, title, description, url}
    Returns list of {company, sector, hq, round, amount, reason, source, url}
    Uses Claude Haiku — ~$0.01 per full scan of all feeds combined.
    """
    if not articles or not ANTHROPIC_API_KEY:
        return []

    client = Anthropic(api_key=ANTHROPIC_API_KEY)

    lines = []
    for i, a in enumerate(articles):
        desc = (a.get("description") or "")[:200]
        entry = f"{i + 1}. [{a['source']}] {a['title']}"
        if desc:
            entry += f" — {desc}"
        lines.append(entry)

    prompt = f"""You are filtering news articles to find recently funded tech startups for a cold email internship campaign.

Target profile: 10-500 employees, Series Seed to C (skip Series D+), tech sectors only (fintech, AI/ML, data tools, BioAI, climate tech, SaaS, health analytics, analytics platforms). Locations: UK, Ireland, Canada, or major EU tech cities (Amsterdam, Paris, Berlin, Stockholm).

For each article describing a qualifying funding round, return a JSON object:
{{"idx": N, "company": "exact company name", "sector": "fintech|data|AI/ML|BioAI|climate|SaaS|healthtech|other", "hq": "City, Country", "round": "Seed|Series A|Series B|Series C|unknown", "amount": "£Xm or $Xm or unknown", "reason": "one-sentence cold email hook specific to this company"}}

Skip: Series D or later, enterprise/public companies (1000+ employees), consumer retail/media, hardware-only, real estate, government, companies outside target locations, or articles that are clearly not about a funding round.

Articles:
{chr(10).join(lines)}

Return only a JSON array. Empty array [] if nothing qualifies. No text outside the JSON."""

    try:
        response = client.messages.create(
            model=EXTRACT_MODEL,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        text = next((b.text for b in response.content if isinstance(b, TextBlock)), "")
        text = re.sub(r"```(?:json)?\s*", "", text)
        m = re.search(r"\[.*\]", text, re.DOTALL)
        if not m:
            return []
        try:
            leads = json.loads(m.group())
        except json.JSONDecodeError as e:
            log.warning("Claude funding JSON parse failed: %s\nRaw text: %.500s", e, text)
            return []
        for lead in leads:
            idx = lead.get("idx", 0) - 1
            if 0 <= idx < len(articles):
                lead["source"] = articles[idx]["source"]
                lead["url"]    = articles[idx].get("url", "")
        return leads
    except Exception as e:
        log.warning("Claude funding extraction failed: %s", e)
        return []

FUNDING_FEEDS = [
    # ── UK ────────────────────────────────────────────────────────────────────
    ("Sifted",        "https://sifted.eu/feed/"),
    # UKTN removed — SSL handshake fails at server level, unreachable from any client
    ("TechCrunch UK", "https://techcrunch.com/tag/united-kingdom/feed/"),
    # ── Canada — catches Toronto/Montreal AI + fintech funding rounds ─────────
    ("BetaKit",       "https://betakit.com/feed/"),
    ("TechCrunch CA", "https://techcrunch.com/tag/canada/feed/"),
    # ── EU — catches Amsterdam/Paris/Berlin rounds for portal monitoring ──────
    ("EU Startups",   "https://eu-startups.com/feed/"),
    ("TechCrunch EU", "https://techcrunch.com/tag/europe/feed/"),
]


def fetch_funding_leads() -> int:
    """
    Parse funding news RSS, extract leads with Claude Haiku, and add
    newly funded companies to the companies table with status='funding_lead'.
    Returns the count of new companies added.
    Cost: ~$0.01 per full scan of all feeds combined.
    """
    articles: list[dict] = []
    seen_titles: set[str] = set()

    for source_name, feed_url in FUNDING_FEEDS:
        batch_count = 0
        try:
            resp = cffi_requests.get(feed_url, impersonate="chrome124", timeout=12)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            for item in root.iter("item"):
                title_el = item.find("title")
                if title_el is None or not title_el.text:
                    continue
                title = title_el.text.strip()
                if not _looks_like_funding_news(title) or title in seen_titles:
                    continue
                seen_titles.add(title)
                desc_el = item.find("description")
                description = ""
                if desc_el is not None and desc_el.text:
                    description = BeautifulSoup(desc_el.text, "lxml").get_text()[:300]
                link_el = item.find("link")
                url = link_el.text.strip() if link_el is not None and link_el.text else ""
                articles.append({"source": source_name, "title": title, "description": description, "url": url})
                batch_count += 1
            console.print(f"  RSS [{source_name}]: {batch_count} candidate headlines")
            time.sleep(0.5)
        except ET.ParseError as e:
            console.print(f"  [yellow]RSS [{source_name}]: XML parse error — {e}[/yellow]")
        except requests.RequestException as e:
            console.print(f"  [yellow]RSS [{source_name}]: request failed — {e}[/yellow]")
        except Exception as e:
            console.print(f"  [yellow]RSS [{source_name}]: {e}[/yellow]")

    if not articles:
        console.print("  No funding candidates found in feeds.")
        return 0

    console.print(f"  [cyan]Sending {len(articles)} headlines to Claude for extraction...[/cyan]")
    leads = _extract_leads_with_claude(articles)
    console.print(f"  [green]Claude identified {len(leads)} relevant funding leads.[/green]")

    added = 0
    seen_companies: set[str] = set()
    for lead in leads:
        name = lead.get("company", "").strip()
        if not name or name in seen_companies:
            continue
        seen_companies.add(name)
        sector   = lead.get("sector", "")
        hq       = lead.get("hq", "")
        amount   = lead.get("amount", "")
        round_t  = lead.get("round", "")
        reason   = lead.get("reason", "")
        source   = lead.get("source", "")
        notes    = f"[FUNDING LEAD — {source}] {round_t} {amount} · {hq} · {reason}"
        upsert_company(
            name=name,
            sector=sector,
            notes=notes[:300],
            status="funding_lead",
        )
        added += 1

    return added


# ── Slug validator ────────────────────────────────────────────────────────────

def validate_all_slugs(verbose: bool = True) -> dict:
    """
    Check every slug in GREENHOUSE_SLUGS and LEVER_SLUGS.
    Dead slugs are cached in DB and auto-skipped on future discovery runs.
    Run: python discover.py validate
    """
    results: dict = {"greenhouse": {}, "lever": {}}

    for slug in GREENHOUSE_SLUGS:
        _, status = fetch_greenhouse_board(slug)
        results["greenhouse"][slug] = status
        if verbose:
            colour = "green" if status == "ok" else "yellow" if status == "dead" else "red"
            console.print(f"  [{colour}]gh/{slug}: {status}[/{colour}]")
        time.sleep(0.3)

    for slug in LEVER_SLUGS:
        _, status = fetch_lever_board(slug)
        results["lever"][slug] = status
        if verbose:
            colour = "green" if status == "ok" else "yellow" if status == "dead" else "red"
            console.print(f"  [{colour}]lever/{slug}: {status}[/{colour}]")
        time.sleep(0.3)

    live_gh  = sum(1 for v in results["greenhouse"].values() if v == "ok")
    live_lv  = sum(1 for v in results["lever"].values() if v == "ok")
    console.print(f"\n[bold]Result:[/bold] {live_gh}/{len(GREENHOUSE_SLUGS)} Greenhouse live · {live_lv}/{len(LEVER_SLUGS)} Lever live")
    return results


# ── Main entry ────────────────────────────────────────────────────────────────

def run_discovery(sources=("remotive", "ats", "reed")) -> dict:
    """
    Run job discovery. sources controls which are active:
      "remotive"       — Remotive remote jobs API
      "ats"            — Greenhouse + Lever ATS boards
      "reed"           — Reed.co.uk (requires REED_API_KEY)
      "funding_leads"  — RSS funding news → companies table (not jobs)
    """
    all_jobs: list[dict] = []

    if "remotive" in sources:
        console.print("[cyan]Remotive...[/cyan]")
        all_jobs.extend(fetch_remotive())

    if "ats" in sources:
        console.print("[cyan]ATS boards (Greenhouse + Lever)...[/cyan]")
        all_jobs.extend(fetch_all_ats())

    if "reed" in sources:
        console.print("[cyan]Reed.co.uk...[/cyan]")
        all_jobs.extend(fetch_reed_jobs())

    if "funding_leads" in sources:
        console.print("[cyan]Funding news...[/cyan]")
        n = fetch_funding_leads()
        console.print(f"  [green]{n} new funding leads added — review in Companies tab[/green]")

    new_count = 0
    for job in all_jobs:
        if not job.get("url"):
            continue
        _, is_new = insert_job(
            title=job["title"],
            company=job["company"],
            location=job.get("location", ""),
            url=job["url"],
            source=job["source"],
            description=job.get("description", ""),
            salary=job.get("salary", ""),
        )
        if is_new:
            new_count += 1

    return {"total_found": len(all_jobs), "new_added": new_count}


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "validate":
        console.print("[bold]Validating all ATS slugs...[/bold]")
        validate_all_slugs()
    elif len(sys.argv) > 1 and sys.argv[1] == "funding":
        console.print("[bold]Scanning funding news...[/bold]")
        n = fetch_funding_leads()
        console.print(f"[green]{n} new funding leads added[/green]")
    else:
        result = run_discovery()
        console.print(f"Done: {result['new_added']} new jobs added ({result['total_found']} found total)")
