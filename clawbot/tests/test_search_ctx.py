"""Tests for SearchClient — noop stub, _LiveSearch wiring, and tools clients."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def test_noop_search_returns_empty():
    from clawbot.skill_ctx import make_noop_ctx

    ctx = make_noop_ctx(caller_id="test", budget_usd=0.0)
    assert asyncio.run(ctx.search.search(query="anything")) == []
    extracted = asyncio.run(ctx.search.extract_url(url="https://example.com"))
    assert extracted == {"url": "https://example.com", "title": "", "markdown": ""}


def test_live_search_skips_when_no_tavily_key():
    """No key → empty list, no API call. Lets agents call search() unconditionally."""
    from clawbot.skill_ctx import _LiveSearch

    s = _LiveSearch(tavily_api_key="", firecrawl_api_key="fc_key")
    assert asyncio.run(s.search(query="anything")) == []


def test_live_search_skips_extract_when_no_firecrawl_key():
    from clawbot.skill_ctx import _LiveSearch

    s = _LiveSearch(tavily_api_key="tv_key", firecrawl_api_key="")
    result = asyncio.run(s.extract_url(url="https://example.com"))
    assert result == {"url": "https://example.com", "title": "", "markdown": ""}


def test_live_search_calls_tavily_when_keyed():
    from clawbot.skill_ctx import _LiveSearch

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "results": [
            {"url": "https://a.example", "title": "A", "content": "snippet", "score": 0.9},
        ]
    }
    mock_response.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    s = _LiveSearch(tavily_api_key="tv_key", firecrawl_api_key="")
    with patch("clawbot.tools.tavily.httpx.AsyncClient", return_value=mock_client):
        results = asyncio.run(s.search(query="UK IR35"))

    mock_client.post.assert_called_once()
    assert len(results) == 1
    assert results[0]["url"] == "https://a.example"
    assert results[0]["score"] == 0.9


def test_live_search_calls_firecrawl_when_keyed():
    from clawbot.skill_ctx import _LiveSearch

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "success": True,
        "data": {"markdown": "# Hello", "metadata": {"title": "Greeting"}},
    }
    mock_response.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    s = _LiveSearch(tavily_api_key="", firecrawl_api_key="fc_key")
    with patch("clawbot.tools.firecrawl.httpx.AsyncClient", return_value=mock_client):
        result = asyncio.run(s.extract_url(url="https://example.com"))

    mock_client.post.assert_called_once()
    call_kwargs = mock_client.post.call_args
    # Auth header carries the key
    assert "Bearer fc_key" in call_kwargs.kwargs["headers"]["Authorization"]
    assert result == {"url": "https://example.com", "title": "Greeting", "markdown": "# Hello"}


def test_tavily_raises_when_no_key():
    from clawbot.tools import tavily

    with pytest.raises(ValueError, match="TAVILY_API_KEY"):
        asyncio.run(tavily.search(api_key="", query="x"))


def test_firecrawl_raises_when_no_key():
    from clawbot.tools import firecrawl

    with pytest.raises(ValueError, match="FIRECRAWL_API_KEY"):
        asyncio.run(firecrawl.extract(api_key="", url="https://example.com"))


def test_firecrawl_raises_when_api_returns_success_false():
    from clawbot.tools import firecrawl

    mock_response = MagicMock()
    mock_response.json.return_value = {"success": False, "error": "rate_limited"}
    mock_response.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("clawbot.tools.firecrawl.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(ValueError, match="rate_limited"):
            asyncio.run(firecrawl.extract(api_key="fc_key", url="https://example.com"))
