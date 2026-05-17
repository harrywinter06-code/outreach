"""IMAP-based verification mail extraction."""
import asyncio
from unittest.mock import MagicMock, patch

import pytest

from clawbot.email_reader import EmailReader, VerificationResult


def _fake_message(to: str, body: str) -> bytes:
    return (
        f"To: {to}\r\n"
        f"From: noreply@service.com\r\n"
        f"Subject: Verify\r\n"
        f"\r\n"
        f"{body}\r\n"
    ).encode("utf-8")


def test_finds_six_digit_code():
    msg = _fake_message("substack+sub123@example.com", "Your code is 482917, valid 10 min.")
    fake_imap = MagicMock()
    fake_imap.search.return_value = ("OK", [b"1"])
    fake_imap.fetch.return_value = ("OK", [(b"1 (RFC822 {123}", msg)])

    reader = EmailReader(host="imap.x", port=993, user="u", password="p", domain="example.com")
    with patch("clawbot.email_reader.imaplib.IMAP4_SSL", return_value=fake_imap):
        result = asyncio.run(reader.find_verification(alias="substack+sub123", since_minutes=10))

    assert isinstance(result, VerificationResult)
    assert result.code == "482917"
    assert result.url is None


def test_finds_confirmation_url():
    body = "Click https://service.com/verify?token=abc123 to confirm."
    msg = _fake_message("medium+m1@example.com", body)
    fake_imap = MagicMock()
    fake_imap.search.return_value = ("OK", [b"7"])
    fake_imap.fetch.return_value = ("OK", [(b"7 (RFC822 {123}", msg)])

    reader = EmailReader(host="x", port=993, user="u", password="p", domain="example.com")
    with patch("clawbot.email_reader.imaplib.IMAP4_SSL", return_value=fake_imap):
        result = asyncio.run(reader.find_verification(alias="medium+m1", since_minutes=10))

    assert result.url == "https://service.com/verify?token=abc123"
    assert result.code is None


def test_returns_none_when_no_match():
    fake_imap = MagicMock()
    fake_imap.search.return_value = ("OK", [b""])  # no message ids
    reader = EmailReader(host="x", port=993, user="u", password="p", domain="example.com")
    with patch("clawbot.email_reader.imaplib.IMAP4_SSL", return_value=fake_imap):
        result = asyncio.run(reader.find_verification(alias="x+y", since_minutes=10))
    assert result is None


def test_alias_isolation_only_matches_alias():
    """A message to a different alias must NOT match — alias is required in TO."""
    msg = _fake_message("OTHER+xyz@example.com", "Code 111111")
    fake_imap = MagicMock()
    fake_imap.search.return_value = ("OK", [b"1"])
    fake_imap.fetch.return_value = ("OK", [(b"1 (RFC822 {123}", msg)])

    reader = EmailReader(host="x", port=993, user="u", password="p", domain="example.com")
    with patch("clawbot.email_reader.imaplib.IMAP4_SSL", return_value=fake_imap):
        result = asyncio.run(reader.find_verification(alias="substack+sub1", since_minutes=10))
    assert result is None
