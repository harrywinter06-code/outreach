"""Tavily search client — LLM-graded web search results.

Free tier: 1k searches/mo. Endpoint: https://api.tavily.com/search.
Returns answer-style snippets pre-filtered for LLM consumption."""
from __future__ import annotations

from typing import Any

import httpx

_ENDPOINT = "https://api.tavily.com/search"
_TIMEOUT_S = 20.0


async def search(
    *,
    api_key: str,
    query: str,
    max_results: int = 5,
    search_depth: str = "basic",
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Return a list of {url, title, content, score} dicts. Raises on HTTP error."""
    if not api_key:
        raise ValueError("TAVILY_API_KEY not set")
    body: dict[str, Any] = {
        "api_key": api_key,
        "query": query,
        "max_results": max_results,
        "search_depth": search_depth,
    }
    if include_domains:
        body["include_domains"] = include_domains
    if exclude_domains:
        body["exclude_domains"] = exclude_domains
    async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
        response = await client.post(_ENDPOINT, json=body)
        response.raise_for_status()
    data = response.json()
    return [
        {
            "url": str(r.get("url", "")),
            "title": str(r.get("title", "")),
            "content": str(r.get("content", "")),
            "score": float(r.get("score", 0.0)),
        }
        for r in data.get("results", [])
    ]
