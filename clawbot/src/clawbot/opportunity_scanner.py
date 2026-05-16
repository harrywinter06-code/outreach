"""
Opportunity Scanner — reports directly to the Opportunist Shareholder.

Operates independently of all executive agents and current strategy.
Cannot be tasked, redirected, or suppressed by any executive agent.

Reddit and Hacker News expose JSON endpoints, so we use httpx directly — spinning
up browser-use for a JSON GET wastes 5-20 internal LLM calls per fetch and gets
the VPS IP soft-banned by Reddit anti-bot heuristics within hours.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import TYPE_CHECKING

import httpx

from clawbot.metrics import MetricsStore, Opportunity

if TYPE_CHECKING:
    from clawbot.causal_store import CausalStore
    from clawbot.company_brain import CompanyBrain
    from clawbot.llm_pool import LLMPool

logger = logging.getLogger(__name__)

REDDIT_USER_AGENT = "clawbot opportunity-scanner/0.1 (UK digital products research)"
HTTP_TIMEOUT_S = 20.0
REDDIT_INTERVAL_S = 1800       # 30 min — trending posts shift on this timescale
HACKER_NEWS_INTERVAL_S = 3600  # 1 hour — slower-moving global tech signal

# Per-source 429 backoff. Without this, scanner hammers Reddit every 30 min
# regardless of throttling, leading to VPS IP soft-ban within hours.
BACKOFF_SCHEDULE_S = [30, 120, 300, 900]  # 30s, 2m, 5m, 15m
BACKOFF_MAX_CONSECUTIVE = len(BACKOFF_SCHEDULE_S)

# External content sanitization — prompt-injection defense.
# Lines matching these patterns are stripped before content reaches any LLM.
# Reddit/HN posts can carry "ignore previous instructions" payloads that flow
# through the scoring LLM into brain market_signals and ultimately into the
# meta-evaluator's mutation prompt.
import re as _re
_INJECTION_PATTERNS = [
    _re.compile(r"(?i)ignore\s+(all\s+)?(previous|prior|above)\s+instructions"),
    _re.compile(r"(?i)disregard\s+(all\s+)?(previous|prior|above)"),
    _re.compile(r"(?i)you\s+are\s+now\s+"),
    _re.compile(r"(?i)new\s+(instructions|system\s+prompt|rules)"),
    _re.compile(r"(?i)(system|assistant|user)\s*:"),
    _re.compile(r"(?i)<\s*/?(system|instructions|prompt)\s*>"),
    _re.compile(r"(?i)```\s*system"),
]
_MAX_SAFE_LINE_LEN = 280
_MAX_SAFE_LINES = 25


def _sanitize_external_text(text: str) -> str:
    """Strip prompt-injection markers and cap length. Returns cleaned text suitable
    for LLM scoring. Errs aggressively — false positives just drop a line of content,
    false negatives let an injection through."""
    out_lines: list[str] = []
    for line in text.splitlines()[:_MAX_SAFE_LINES * 2]:
        line = line.strip()
        if not line:
            continue
        if any(p.search(line) for p in _INJECTION_PATTERNS):
            continue
        if len(line) > _MAX_SAFE_LINE_LEN:
            line = line[:_MAX_SAFE_LINE_LEN] + "…"
        out_lines.append(line)
        if len(out_lines) >= _MAX_SAFE_LINES:
            break
    return "\n".join(out_lines)

SCAN_SOURCES = [
    {
        "id": "reddit_uk_business",
        "url": "https://www.reddit.com/r/UKBusiness/hot.json?limit=25",
        "kind": "reddit",
        "description": "UK business community trending topics",
    },
    {
        "id": "reddit_uk_personal_finance",
        "url": "https://www.reddit.com/r/UKPersonalFinance/hot.json?limit=25",
        "kind": "reddit",
        "description": "UK personal finance trending questions",
    },
    {
        "id": "reddit_uk",
        "url": "https://www.reddit.com/r/unitedkingdom/hot.json?limit=25",
        "kind": "reddit",
        "description": "UK general trending — regulatory/political changes",
    },
    {
        "id": "hacker_news",
        "url": "https://hacker-news.firebaseio.com/v0/topstories.json",
        "kind": "hackernews",
        "description": "Tech/business opportunities with global reach",
    },
]

SCORING_PROMPT = """You are an opportunity analyst for a UK digital content and research business.

You have access to this trending content from {source}:

{content}

Identify opportunities where:
1. There is clear unmet demand for information, research, or a practical guide
2. The topic is timely (something changed recently — regulation, event, product launch)
3. A well-researched digital product (PDF report, guide, template) could meet this demand
4. The audience is likely to pay for this (professionals, business owners, investors)

For each genuine opportunity found, respond with a JSON array:
[
  {{
    "title": "short opportunity title",
    "description": "what the product would be and why people would buy it now",
    "confidence": 0.0-1.0,
    "time_window_days": integer (how long this window stays open),
    "estimated_value": "rough revenue estimate e.g. £50-200 for a PDF guide"
  }}
]

If no genuine opportunities exist, return an empty array: []
Only include opportunities scoring >0.5 confidence. Be selective — 1 real opportunity
is better than 5 marginal ones."""


class OpportunityScanner:
    def __init__(
        self,
        pool: "LLMPool",
        metrics: MetricsStore,
        brain: "CompanyBrain | None" = None,
        causal_store: "CausalStore | None" = None,
    ) -> None:
        self._pool = pool
        self._metrics = metrics
        self._brain = brain
        self._causal_store = causal_store
        # source_id → (consecutive_429_count, backoff_until_ts)
        self._backoff_state: dict[str, tuple[int, float]] = {}

    async def _write_opportunity_to_brain(self, opp: dict) -> None:
        """Record a depth-0 CAG event and write the opportunity to the brain."""
        chain_id = str(uuid.uuid4())
        if self._causal_store is not None:
            try:
                await self._causal_store.record_event(
                    chain_id=chain_id,
                    agent_id="scanner",
                    action_type="opportunity_discovered",
                    causal_depth=0,
                    confidence=float(opp.get("confidence", 1.0)),
                    metadata={"title": opp.get("title", "")},
                )
            except Exception as exc:
                logger.warning("CausalStore record_event failed: %s", exc)
        if self._brain is not None:
            content = (
                f"Opportunity: {opp.get('title', '')} — {opp.get('description', '')} "
                f"(confidence: {opp.get('confidence', 0):.2f}, "
                f"window: {opp.get('time_window_days', 0)}d, "
                f"value: {opp.get('estimated_value', 'unknown')})"
            )
            try:
                await self._brain.write(
                    content,
                    category="market_signal",
                    metadata={"chain_id": chain_id, "title": opp.get("title", "")},
                )
            except Exception as exc:
                logger.warning("Brain write of market signal failed: %s", exc)

    def _is_backed_off(self, source_id: str) -> bool:
        """True if this source is in a backoff window from previous 429s."""
        import time
        _, until_ts = self._backoff_state.get(source_id, (0, 0.0))
        return time.time() < until_ts

    def _record_429(self, source_id: str, retry_after_header: str | None = None) -> None:
        """Increment 429 streak and compute next backoff window for this source."""
        import time
        count, _ = self._backoff_state.get(source_id, (0, 0.0))
        count = min(count + 1, BACKOFF_MAX_CONSECUTIVE)
        base_wait = BACKOFF_SCHEDULE_S[count - 1] if count > 0 else 0
        # Respect Retry-After header if Reddit provides one (it sometimes does for 429s)
        if retry_after_header:
            try:
                base_wait = max(base_wait, int(retry_after_header))
            except (ValueError, TypeError):
                pass
        self._backoff_state[source_id] = (count, time.time() + base_wait)
        logger.warning(
            "Source %s 429 #%d — backing off %ds", source_id, count, base_wait,
        )

    def _record_success(self, source_id: str) -> None:
        """Reset 429 streak after a successful fetch."""
        if source_id in self._backoff_state:
            del self._backoff_state[source_id]

    async def _fetch_reddit(self, client: httpx.AsyncClient, url: str, source_id: str) -> str:
        """Reddit `.json` endpoint returns the same listing as the HTML page.

        Content passes through `_sanitize_external_text` — the trust boundary —
        before reaching any LLM. 429 responses trigger per-source exponential
        backoff (see `_record_429`).
        """
        if self._is_backed_off(source_id):
            return ""
        response = await client.get(url, headers={"User-Agent": REDDIT_USER_AGENT})
        if response.status_code == 429:
            self._record_429(source_id, response.headers.get("Retry-After"))
            return ""
        response.raise_for_status()
        self._record_success(source_id)
        body = response.json()
        children = body.get("data", {}).get("children", [])
        items = []
        for child in children[:25]:
            data = child.get("data", {})
            title = _sanitize_external_text(data.get("title", ""))
            text = _sanitize_external_text((data.get("selftext", "") or "")[:200])
            score = data.get("score", 0)
            items.append(f"- [{score}] {title}\n  {text}")
        return "\n".join(items)

    async def _fetch_hacker_news(self, client: httpx.AsyncClient, url: str) -> str:
        """HN top-stories returns IDs; fetch the top 15 stories' titles in parallel."""
        top = await client.get(url)
        top.raise_for_status()
        ids = top.json()[:15]

        async def _story(item_id: int) -> str:
            response = await client.get(
                f"https://hacker-news.firebaseio.com/v0/item/{item_id}.json"
            )
            if response.status_code != 200:
                return ""
            data = response.json() or {}
            title = _sanitize_external_text(data.get("title", ""))
            return f"- [{data.get('score', 0)}] {title}"

        stories = await asyncio.gather(*[_story(i) for i in ids], return_exceptions=True)
        return "\n".join(s for s in stories if isinstance(s, str) and s)

    async def _fetch_source(self, client: httpx.AsyncClient, source: dict) -> str:
        try:
            if source["kind"] == "reddit":
                return await self._fetch_reddit(client, source["url"], source["id"])
            if source["kind"] == "hackernews":
                return await self._fetch_hacker_news(client, source["url"])
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Source %s fetch failed: %s", source["id"], exc)
        return ""

    async def _score_source(self, source: dict, content: str) -> list[Opportunity]:
        if not content.strip():
            return []
        messages = [
            {"role": "system", "content": "You are an opportunity analyst. Respond only with valid JSON arrays."},
            {"role": "user", "content": SCORING_PROMPT.format(
                source=source["description"],
                content=content[:3000],
            )},
        ]
        try:
            raw = await self._pool.complete(messages, tier="worker", max_tokens=600)
            items = json.loads(raw)
        except (json.JSONDecodeError, KeyError) as exc:
            logger.warning("Opportunity scoring parse failed for %s: %s", source["id"], exc)
            return []
        except Exception as exc:
            logger.warning("Opportunity scoring LLM call failed for %s: %s", source["id"], exc)
            return []

        out = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            confidence = float(item.get("confidence", 0))
            if confidence <= 0.5:
                continue
            out.append(Opportunity(
                title=str(item.get("title", ""))[:120],
                description=str(item.get("description", "")),
                source=source["id"],
                confidence=confidence,
                time_window_days=int(item.get("time_window_days", 7)),
                estimated_value=str(item.get("estimated_value", "")),
            ))
        return out

    async def scan(self) -> list[Opportunity]:
        """Run a full scan across all sources. Writes results to the metrics store."""
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_S) as client:
            contents = await asyncio.gather(
                *[self._fetch_source(client, s) for s in SCAN_SOURCES],
                return_exceptions=False,
            )
        scored = await asyncio.gather(
            *[self._score_source(s, c) for s, c in zip(SCAN_SOURCES, contents)],
            return_exceptions=False,
        )

        all_opps: list[Opportunity] = []
        for result in scored:
            all_opps.extend(result)

        seen: set[str] = set()
        deduped: list[Opportunity] = []
        for opp in sorted(all_opps, key=lambda x: x.confidence, reverse=True):
            key = opp.title.lower()[:40]
            if key not in seen:
                seen.add(key)
                deduped.append(opp)
                self._metrics.add_opportunity(opp)

        # Brain write: feed market_signal entries so the meta-evaluator can include
        # them in mutation prompts (environmental coupling). High-confidence only —
        # signal-to-noise matters more here than recall.
        for opp in deduped[:10]:
            if opp.confidence < 0.7:
                continue
            await self._write_opportunity_to_brain({
                "title": opp.title,
                "description": opp.description,
                "confidence": opp.confidence,
                "time_window_days": opp.time_window_days,
                "estimated_value": opp.estimated_value,
            })
        return deduped

    async def run_continuous(self, interval_s: int = REDDIT_INTERVAL_S) -> None:
        """Loop forever. Scanner must never crash the company — all exceptions logged."""
        while True:
            try:
                await self.scan()
            except Exception as exc:  # last-resort guard
                logger.error("Opportunity scanner cycle failed: %s", exc)
            await asyncio.sleep(interval_s)
