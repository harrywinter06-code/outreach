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
    """Fetch URL and return extracted plaintext. Raises on HTTP error or timeout."""
    async with httpx.AsyncClient(
        timeout=_HTTP_TIMEOUT_S, headers=_HEADERS, follow_redirects=True,
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    if "html" in content_type:
        return _strip_html(response.text)
    return response.text[:_MAX_CONTENT_CHARS]
