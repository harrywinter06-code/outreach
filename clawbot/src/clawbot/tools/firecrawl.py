"""Firecrawl extraction client — URL → clean LLM-ready markdown.

Free tier: 500 pages/mo. Endpoint: https://api.firecrawl.dev/v1/scrape.
Strips boilerplate, ads, navigation. Caller is responsible for prompt-injection
sanitization downstream — Firecrawl returns whatever the page contains."""
from __future__ import annotations

from typing import Any

import httpx

_ENDPOINT = "https://api.firecrawl.dev/v1/scrape"
_TIMEOUT_S = 30.0


async def extract(*, api_key: str, url: str) -> dict[str, Any]:
    """Return {url, title, markdown}. Raises on HTTP error or invalid response."""
    if not api_key:
        raise ValueError("FIRECRAWL_API_KEY not set")
    async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
        response = await client.post(
            _ENDPOINT,
            json={"url": url, "formats": ["markdown"]},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        response.raise_for_status()
    data = response.json()
    if not data.get("success"):
        raise ValueError(f"Firecrawl returned success=false for {url}: {data.get('error', '')}")
    payload = data.get("data") or {}
    metadata = payload.get("metadata") or {}
    return {
        "url": url,
        "title": str(metadata.get("title", "")),
        "markdown": str(payload.get("markdown", "")),
    }
