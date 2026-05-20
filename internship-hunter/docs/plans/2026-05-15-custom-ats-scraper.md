# Custom ATS Scraper (Workday / Ashby / custom career pages)

> **For agentic workers:** Use superpowers:executing-plans to implement task-by-task.

**Goal:** Add a ScrapeGraphAI + NVIDIA NIM scraper that pulls internship listings from companies whose career pages aren't on Greenhouse or Lever.

**Architecture:** New `ats_scraper.py` wraps ScrapeGraphAI's `SmartScraperGraph` pointed at a free NVIDIA NIM endpoint. A curated list of `(company, career_url)` pairs lives in the same file. `discover.py` calls it as a new `"custom_ats"` source alongside the existing Greenhouse/Lever/Remotive/Reed sources.

**Tech Stack:** `scrapegraphai`, NVIDIA NIM (openai-compatible, free tier), existing `requests`/`config`/`tracker` patterns.

---

## Task 1 — Config + dependency

**Files:**
- Modify: `config.py`
- Modify: `pyproject.toml`

- [ ] Add `NVIDIA_NIM_API_KEY` to `config.py` following the existing optional pattern:

```python
NVIDIA_NIM_API_KEY: str = os.getenv("NVIDIA_NIM_API_KEY", "")
```

Add it to `__all__`.

- [ ] Add to `.env.example` (create if missing):

```
NVIDIA_NIM_API_KEY=your_key_here  # free at build.nvidia.com
```

- [ ] Add `scrapegraphai` to `pyproject.toml` dependencies:

```toml
[project]
dependencies = [
    "scrapegraphai>=1.13",
    # ...existing deps
]
```

- [ ] Install: `uv add scrapegraphai`

- [ ] Commit: `git commit -m "feat: add nvidia nim config + scrapegraphai dep"`

---

## Task 2 — `ats_scraper.py`

**Files:**
- Create: `internship-hunter/ats_scraper.py`
- Create: `internship-hunter/tests/test_ats_scraper.py`

The module has two responsibilities: the NIM-backed scraper function, and the curated target list.

- [ ] Write the failing test first:

```python
# tests/test_ats_scraper.py
from unittest.mock import patch, MagicMock
from ats_scraper import scrape_career_page, CUSTOM_ATS_TARGETS

def test_scrape_returns_list_of_jobs():
    mock_result = [{"title": "Data Intern", "location": "London", "url": "https://example.com/job/1"}]
    with patch("ats_scraper.SmartScraperGraph") as MockGraph:
        instance = MockGraph.return_value
        instance.run.return_value = {"jobs": mock_result}
        result = scrape_career_page("Acme", "https://acme.com/careers", api_key="test-key")
    assert isinstance(result, list)
    assert result[0]["company"] == "Acme"
    assert result[0]["title"] == "Data Intern"

def test_scrape_returns_empty_on_failure():
    with patch("ats_scraper.SmartScraperGraph") as MockGraph:
        MockGraph.return_value.run.side_effect = Exception("timeout")
        result = scrape_career_page("Acme", "https://acme.com/careers", api_key="test-key")
    assert result == []

def test_targets_list_is_nonempty():
    assert len(CUSTOM_ATS_TARGETS) > 0
    for company, url in CUSTOM_ATS_TARGETS:
        assert company and url.startswith("http")
```

- [ ] Run: `pytest tests/test_ats_scraper.py -v` — expect FAIL (ImportError)

- [ ] Implement `ats_scraper.py`:

```python
"""ScrapeGraphAI-based scraper for Workday, Ashby, and custom career pages.

Targets companies not covered by the Greenhouse/Lever ATS boards in discover.py.
Uses NVIDIA NIM as a free LLM backend (40 RPM limit — sufficient for batch runs).
"""
from __future__ import annotations

import logging
from typing import Any

from scrapegraphai.graphs import SmartScraperGraph

from config import NVIDIA_NIM_API_KEY, TARGET_KEYWORDS, EXCLUDE_KEYWORDS

__all__ = ["CUSTOM_ATS_TARGETS", "scrape_career_page", "fetch_custom_ats"]

log = logging.getLogger(__name__)

_SCRAPE_PROMPT = (
    "Find all internship or intern job listings on this careers page. "
    "For each, return: title, location, and the direct application URL. "
    "Only include roles with 'intern' or 'internship' in the title. "
    "Return a JSON object with key 'jobs' containing a list of objects "
    "with keys: title, location, url."
)

# Companies NOT on Greenhouse/Lever — Workday, Ashby, or custom pages.
# Add new targets here as a (company_name, career_page_url) tuple.
CUSTOM_ATS_TARGETS: list[tuple[str, str]] = [
    # UK fintech / quant
    ("Revolut",             "https://www.revolut.com/careers"),
    ("Monzo",               "https://monzo.com/careers"),       # backup: also on GH
    ("Oaknorth",            "https://www.oaknorth.com/careers"),
    ("Zilch",               "https://zilch.com/careers"),
    # Quant / trading (custom pages, not on any public ATS API)
    ("Optiver",             "https://optiver.com/working-at-optiver/career-opportunities"),
    ("Jane Street",         "https://www.janestreet.com/join-jane-street/open-roles"),
    ("Hudson River Trading","https://www.hudsonrivertrading.com/careers"),
    ("IMC Trading",         "https://www.imc.com/eu/careers"),
    # UK AI / data
    ("Palantir UK",         "https://jobs.lever.co/palantir"),  # also on Lever but UK filter
    ("Wayve",               "https://wayve.ai/join"),
    ("Faculty AI",          "https://faculty.ai/company/careers"),
    ("Graphcore",           "https://www.graphcore.ai/careers"),
    # EU
    ("Adyen",               "https://www.adyen.com/careers"),
    ("Mollie",              "https://www.mollie.com/careers"),
]


def _nim_config(api_key: str) -> dict[str, Any]:
    return {
        "llm": {
            "model": "openai/meta/llama-3.1-8b-instruct",
            "api_key": api_key,
            "openai_api_base": "https://integrate.api.nvidia.com/v1",
            "temperature": 0,
        },
        "verbose": False,
        "headless": True,
    }


def _is_relevant(title: str) -> bool:
    t = title.lower()
    if any(kw.lower() in t for kw in EXCLUDE_KEYWORDS):
        return False
    return "intern" in t or any(kw.lower() in t for kw in TARGET_KEYWORDS)


def scrape_career_page(
    company: str,
    url: str,
    api_key: str,
) -> list[dict[str, Any]]:
    """Scrape one career page. Returns normalised job dicts. Never raises."""
    try:
        graph = SmartScraperGraph(
            prompt=_SCRAPE_PROMPT,
            source=url,
            config=_nim_config(api_key),
        )
        raw = graph.run()
    except Exception as e:
        log.warning("ScrapeGraph failed for %s (%s): %s", company, url, e)
        return []

    jobs_raw = raw.get("jobs") if isinstance(raw, dict) else []
    if not isinstance(jobs_raw, list):
        return []

    results = []
    for job in jobs_raw:
        title = str(job.get("title") or "")
        if not title or not _is_relevant(title):
            continue
        results.append({
            "title":       title,
            "company":     company,
            "location":    str(job.get("location") or ""),
            "url":         str(job.get("url") or url),
            "source":      "CustomATS",
            "description": "",
            "salary":      "",
        })
    return results


def fetch_custom_ats(api_key: str = "") -> list[dict[str, Any]]:
    """Scrape all CUSTOM_ATS_TARGETS. Skips silently if no api_key."""
    key = api_key or NVIDIA_NIM_API_KEY
    if not key:
        log.warning("NVIDIA_NIM_API_KEY not set — skipping custom ATS scrape")
        return []

    all_jobs: list[dict[str, Any]] = []
    for company, url in CUSTOM_ATS_TARGETS:
        jobs = scrape_career_page(company, url, key)
        if jobs:
            log.info("CustomATS/%s: %d relevant", company, len(jobs))
        all_jobs.extend(jobs)
    return all_jobs
```

- [ ] Run: `pytest tests/test_ats_scraper.py -v` — expect PASS

- [ ] Commit: `git commit -m "feat: add custom ATS scraper (scrapegraphai + nvidia nim)"`

---

## Task 3 — Wire into `discover.py`

**Files:**
- Modify: `internship-hunter/discover.py`

- [ ] Add import at top of `discover.py`:

```python
from ats_scraper import fetch_custom_ats
```

- [ ] Add to `run_discovery()` alongside the existing sources:

```python
if "custom_ats" in sources:
    console.print("[cyan]Custom ATS (Workday/Ashby/custom pages)...[/cyan]")
    all_jobs.extend(fetch_custom_ats())
```

- [ ] Update the default sources tuple to include it:

```python
def run_discovery(sources: tuple[str, ...] = ("remotive", "ats", "reed", "custom_ats")) -> dict[str, int]:
```

- [ ] Run full discovery smoke test: `python discover.py` — confirm it runs without error, custom ATS source appears in output (may return 0 jobs if NIM key not set, which is expected and logged).

- [ ] Commit: `git commit -m "feat: wire custom ATS scraper into run_discovery"`

---

## Expanding later

- Increase `CUSTOM_ATS_TARGETS` — low-effort wins for any company with a public career URL
- Add rate-limit awareness (NIM free tier is 40 RPM — add `time.sleep(1.5)` between calls if hitting limits)
- Swap NIM model for a larger one (Llama 3.3 70B) if extraction quality is poor on complex pages
- Cache raw HTML to avoid re-scraping on repeated runs
