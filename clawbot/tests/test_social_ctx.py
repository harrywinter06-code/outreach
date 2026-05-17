"""Tests for SocialClient — noop stub and _LiveSocial API calls."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def test_noop_social_returns_stub_id():
    from clawbot.skill_ctx import make_noop_ctx

    ctx = make_noop_ctx(caller_id="test", budget_usd=0.0)
    result = asyncio.run(ctx.social.x_post(text="hello"))
    assert isinstance(result.get("id"), str)
    assert result["id"].startswith("noop_")


def test_live_x_post_calls_v2_api():
    from clawbot.skill_ctx import _LiveSocial

    mock_response = MagicMock()
    mock_response.json.return_value = {"data": {"id": "tweet_abc123"}}
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    social = _LiveSocial(x_bearer="test_bearer", linkedin_token="", reddit_creds=None)

    with patch("clawbot.skill_ctx.httpx.AsyncClient", return_value=mock_client):
        result = asyncio.run(social.x_post(text="hello world"))

    mock_client.post.assert_called_once()
    call_kwargs = mock_client.post.call_args
    assert "/2/tweets" in call_kwargs[0][0]
    assert result == {"id": "tweet_abc123"}


def test_live_linkedin_post_requires_token():
    from clawbot.skill_ctx import _LiveSocial

    social = _LiveSocial(x_bearer="", linkedin_token="", reddit_creds=None)
    with pytest.raises(ValueError, match="LINKEDIN_ACCESS_TOKEN"):
        asyncio.run(social.linkedin_post(text="hi"))
