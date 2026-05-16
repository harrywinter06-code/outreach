"""Lightweight HTTP research tool for agent-directed web fetches."""
from __future__ import annotations

import logging
import re

import httpx

logger = logging.getLogger(__name__)
_HTTP_TIMEOUT_S = 15.0
_MAX_CONTENT_CHARS = 8_000
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ClawbotResearch/0.1)",
    "Accept": "text/html,text/plain,*/*",
}

# Prompt-injection defence — same threat model as opportunity_scanner.
# Web pages can contain adversarial payloads ("ignore previous instructions")
# that would flow through the brain into evolution mutation prompts.
_INJECTION_PATTERNS = [
    re.compile(r"(?i)ignore\s+(all\s+)?(previous|prior|above)\s+instructions"),
    re.compile(r"(?i)disregard\s+(all\s+)?(previous|prior|above)"),
    re.compile(r"(?i)you\s+are\s+now\s+"),
    re.compile(r"(?i)new\s+(instructions|system\s+prompt|rules)"),
    re.compile(r"(?i)(system|assistant|user)\s*:"),
    re.compile(r"(?i)<\s*/?(system|instructions|prompt)\s*>"),
    re.compile(r"(?i)```\s*system"),
]


def _sanitize(text: str) -> str:
    """Strip prompt-injection markers from fetched web content."""
    return "\n".join(
        line for line in text.splitlines()
        if not any(p.search(line) for p in _INJECTION_PATTERNS)
    )


def _strip_html(html: str) -> str:
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:_MAX_CONTENT_CHARS]


async def fetch_and_extract(url: str) -> str:
    """Fetch URL and return sanitized plaintext. Raises on HTTP error or timeout."""
    async with httpx.AsyncClient(
        timeout=_HTTP_TIMEOUT_S, headers=_HEADERS, follow_redirects=True,
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    raw = _strip_html(response.text) if "html" in content_type else response.text[:_MAX_CONTENT_CHARS]
    return _sanitize(raw)
