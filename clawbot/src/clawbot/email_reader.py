"""IMAP poller for verification mails.

Looks for mail to alias@email_domain within the last N minutes, returns
either a confirmation URL or a 6-digit numeric code. Blocking imaplib is
wrapped in asyncio.to_thread to stay event-loop-safe (matches the
_LivePayments Stripe pattern)."""
from __future__ import annotations

import asyncio
import email
import imaplib
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, UTC

logger = logging.getLogger(__name__)

_URL_RE = re.compile(
    r"https?://[^\s<>\"']+(?:verify|confirm|activate|validate)[^\s<>\"']*",
    re.IGNORECASE,
)
_CODE_RE = re.compile(r"\b(\d{6})\b")
_HTML_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class VerificationResult:
    url: str | None
    code: str | None


class EmailReader:
    def __init__(self, *, host: str, port: int, user: str, password: str, domain: str) -> None:
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._domain = domain

    async def find_verification(
        self, *, alias: str, since_minutes: int = 10
    ) -> VerificationResult | None:
        """Search inbox for the latest mail to alias@domain, return URL or 6-digit code."""
        return await asyncio.to_thread(self._sync_find, alias, since_minutes)

    def _sync_find(self, alias: str, since_minutes: int) -> "VerificationResult | None":
        target_address = f"{alias}@{self._domain}".lower()
        since = datetime.now(UTC) - timedelta(minutes=since_minutes)
        since_str = since.strftime("%d-%b-%Y")
        imap: "imaplib.IMAP4_SSL | None" = None
        try:
            imap = imaplib.IMAP4_SSL(self._host, self._port)
            imap.login(self._user, self._password)
            imap.select("INBOX")
            status, data = imap.search(None, f'(SINCE "{since_str}")')
            if status != "OK" or not data or not data[0]:
                return None
            # Cap at the 50 most recent matches — IMAP SINCE is date-granular,
            # so a busy inbox can yield hundreds of hits for a 10-minute query.
            msg_ids = data[0].split()[-50:]
            for msg_id in reversed(msg_ids):  # newest first
                status, msg_data = imap.fetch(msg_id, "(RFC822)")
                if status != "OK" or not msg_data:
                    continue
                raw = msg_data[0][1] if isinstance(msg_data[0], tuple) else msg_data[0]
                if not isinstance(raw, bytes):
                    continue
                msg = email.message_from_bytes(raw)
                to_header = (msg.get("To") or "").lower()
                if target_address not in to_header:
                    continue
                body = self._extract_body(msg)
                url_match = _URL_RE.search(body)
                if url_match:
                    return VerificationResult(url=url_match.group(0), code=None)
                code_match = _CODE_RE.search(body)
                if code_match:
                    return VerificationResult(url=None, code=code_match.group(1))
            return None
        except Exception as exc:
            logger.warning("IMAP fetch failed: %s", exc)
            return None
        finally:
            if imap is not None:
                try:
                    imap.close()
                    imap.logout()
                except Exception:
                    pass

    @staticmethod
    def _extract_body(msg: "email.message.Message") -> str:
        if msg.is_multipart():
            plain_parts: list[str] = []
            html_parts: list[str] = []
            for part in msg.walk():
                ct = part.get_content_type()
                if ct == "text/plain":
                    payload = part.get_payload(decode=True)
                    if isinstance(payload, bytes):
                        decoded = payload.decode("utf-8", errors="replace")
                        if decoded.strip():
                            plain_parts.append(decoded)
                elif ct == "text/html":
                    payload = part.get_payload(decode=True)
                    if isinstance(payload, bytes):
                        html_parts.append(payload.decode("utf-8", errors="replace"))
            if plain_parts:
                return "\n".join(plain_parts)
            # Return raw HTML: _URL_RE excludes <>"' so it matches href values
            # correctly. Strip tags only when falling back to code detection so
            # digit sequences inside tag attributes aren't false positives.
            html = "\n".join(html_parts)
            if _URL_RE.search(html):
                return html
            return _HTML_TAG_RE.sub(" ", html)
        payload = msg.get_payload(decode=True)
        if isinstance(payload, bytes):
            return payload.decode("utf-8", errors="replace")
        return str(payload or "")
