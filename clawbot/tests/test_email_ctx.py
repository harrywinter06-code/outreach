"""Tests for EmailClient — noop stub and _LiveEmail API calls."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def test_noop_email_send_returns_ok():
    from clawbot.skill_ctx import make_noop_ctx

    ctx = make_noop_ctx(caller_id="test", budget_usd=0.0)
    result = asyncio.run(ctx.email.send(to="a@b.com", subject="Hi", body_text="hello"))
    assert result.get("ok") is True
    assert result.get("id") == "noop_email"


def test_live_email_send_requires_key():
    from clawbot.skill_ctx import _LiveEmail

    emailer = _LiveEmail(resend_key="", from_address="bot@example.com")
    with pytest.raises(ValueError, match="RESEND_API_KEY"):
        asyncio.run(emailer.send(to="a@b.com", subject="Hi", body_text="hello"))


def test_live_email_verify_syntax_fallback():
    from clawbot.skill_ctx import _LiveEmail

    emailer = _LiveEmail(resend_key="fake_key", from_address="bot@example.com", bouncer_key="")

    valid = asyncio.run(emailer.verify_address("user@example.com"))
    assert valid["deliverable"] is True

    invalid = asyncio.run(emailer.verify_address("not-an-email"))
    assert invalid["deliverable"] is False
