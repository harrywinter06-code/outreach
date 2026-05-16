"""
Telegram bot channel for operator escalations — outbound + inbound.

Outbound: `TelegramSender.send_escalation(esc)` posts to the Bot API's
sendMessage. The body is HTML-formatted with an [esc:<id>] tag so replies
can be matched back.

Inbound: `TelegramReceiver.poll_forever()` long-polls getUpdates. Two reply
mechanisms supported, both write into the same `/metrics/escalation_replies.jsonl`
that the rest of the system already consumes:

    1. Slash command: `/reply <escalation_id> <text>`
    2. Telegram's reply-to-message: long-press the bot's escalation message →
       Reply → type your response. The receiver finds the [esc:<id>] tag in
       the original message text and uses the rest of the user message as
       the reply body.

Authentication: only messages where `chat.id == TELEGRAM_CHAT_ID` are honoured.
Any other user who messages the bot is silently ignored — the bot can't be
used to inject replies by random Telegram users who discover its name.

Offset persistence: getUpdates offset is stored in /metrics/telegram_offset
so a scheduler restart doesn't reprocess all historical messages.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from clawbot.escalation import Escalation

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"
LONG_POLL_TIMEOUT_S = 30
HTTP_TIMEOUT_S = LONG_POLL_TIMEOUT_S + 10  # must exceed long-poll
_ESC_TAG_RE = re.compile(r"\[esc:([a-f0-9]{6,32})\]")
_SLASH_REPLY_RE = re.compile(r"^/reply\s+([a-f0-9]{6,32})\s+(.+)$", re.DOTALL)

# Severity tone — casual by default; urgent stays alarm-shaped because it should.
_CASUAL_OPENERS = {
    "info": "",          # no header — flows like a text
    "request": "👋 ",
    "warning": "⚠️ ",
    "urgent": "🚨 urgent — ",
}
_AGENT_DISPLAY = {
    "ceo": "your CEO",
    "cfo": "your CFO",
    "cmo": "your CMO",
    "coo": "your COO",
    "cto": "your CTO",
    "meta": "Meta (the evaluator)",
    "board": "the board",
}


class TelegramSender:
    """Outbound: escalation → Telegram chat."""

    def __init__(self, bot_token: str, chat_id: str) -> None:
        if not bot_token or not chat_id:
            raise ValueError("Telegram bot_token and chat_id are both required")
        self._token = bot_token
        self._chat_id = chat_id

    def _send_url(self) -> str:
        return f"{TELEGRAM_API}/bot{self._token}/sendMessage"

    async def send_escalation(self, esc: "Escalation") -> int | None:
        """Send the escalation as a Telegram message — casual by default.
        Returns message_id on success, None on failure (never raises)."""
        body = _format_escalation_body(esc)
        return await self._send_html(body)

    async def send_text(self, text: str, footer: str = "") -> int | None:
        """Send a free-form message (used for chat responses, not escalations).
        Text is HTML-escaped; footer is appended verbatim (caller supplies safe HTML)."""
        body = _html_escape(text)
        if footer:
            body = f"{body}\n\n<i>{footer}</i>"
        return await self._send_html(body)

    async def _send_html(self, body: str) -> int | None:
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_S) as client:
                resp = await client.post(
                    self._send_url(),
                    json={
                        "chat_id": self._chat_id,
                        "text": body,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": True,
                    },
                )
            if resp.status_code != 200:
                logger.warning("Telegram send failed: %d %s", resp.status_code, resp.text[:200])
                return None
            data = resp.json()
            if not data.get("ok"):
                logger.warning("Telegram API returned not-ok: %s", data.get("description"))
                return None
            return int(data["result"]["message_id"])
        except (httpx.HTTPError, OSError, KeyError, ValueError) as exc:
            logger.warning("Telegram send raised %s", exc)
            return None


def _format_escalation_body(esc: "Escalation") -> str:
    """Casual escalation format: feels like a text from a colleague.
    Urgent escalations keep an alarm shape because they should look different."""
    role = _AGENT_DISPLAY.get(esc.from_agent, esc.from_agent)
    opener = _CASUAL_OPENERS.get(esc.severity, "")
    if esc.severity == "urgent":
        # Alarm-shaped — don't blend in with chat
        header = f"{opener}<b>{_html_escape(role)}</b>"
        body = f"{header}\n\n<b>{_html_escape(esc.summary)}</b>\n\n{_html_escape(esc.detail[:1500])}"
    else:
        # Conversational — opens like a message, not a notification
        header = f"{opener}<b>{_html_escape(role)} here</b>"
        body = f"{header}\n\n{_html_escape(esc.summary)}"
        if esc.detail and esc.detail.strip() not in esc.summary:
            body += f"\n\n{_html_escape(esc.detail[:1500])}"
    body += f"\n\n<i>— hit reply, or /reply {esc.id} </i><code>[esc:{esc.id}]</code>"
    return body


class TelegramReceiver:
    """Inbound: long-polls Telegram, writes operator replies into the JSONL the
    scheduler's `_operator_reply_loop` already drains."""

    def __init__(self, bot_token: str, chat_id: str, metrics_dir: Path) -> None:
        if not bot_token or not chat_id:
            raise ValueError("Telegram bot_token and chat_id are both required")
        self._token = bot_token
        # Telegram sends chat.id as int; normalise once.
        self._chat_id_int = int(chat_id)
        self._metrics_dir = metrics_dir

    def _updates_url(self) -> str:
        return f"{TELEGRAM_API}/bot{self._token}/getUpdates"

    def _offset_path(self) -> Path:
        return self._metrics_dir / "telegram_offset"

    def _load_offset(self) -> int:
        try:
            return int(self._offset_path().read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return 0

    def _save_offset(self, offset: int) -> None:
        try:
            self._metrics_dir.mkdir(parents=True, exist_ok=True)
            self._offset_path().write_text(str(offset), encoding="utf-8")
        except OSError as exc:
            logger.warning("Could not persist Telegram offset: %s", exc)

    async def _fetch_updates(self, client: httpx.AsyncClient) -> list[dict]:
        offset = self._load_offset()
        try:
            resp = await client.get(
                self._updates_url(),
                params={
                    "offset": offset,
                    "timeout": LONG_POLL_TIMEOUT_S,
                    "allowed_updates": json.dumps(["message"]),
                },
            )
        except httpx.HTTPError as exc:
            logger.warning("Telegram getUpdates failed: %s", exc)
            return []
        if resp.status_code != 200:
            logger.warning("Telegram getUpdates returned %d", resp.status_code)
            return []
        body = resp.json()
        if not body.get("ok"):
            logger.warning("Telegram getUpdates not-ok: %s", body.get("description"))
            return []
        return body.get("result", [])

    def _classify_message(self, message: dict) -> tuple[str, tuple[str, str] | str] | None:
        """Classify an inbound Telegram message:
        - ("reply", (escalation_id, reply_text)) — answers an existing escalation
        - ("chat", text) — free-form message from the operator (no escalation context)
        - None — empty / unparseable
        """
        text = (message.get("text") or "").strip()
        if not text:
            return None

        # Slash-reply: always a reply, even if no escalation actually has that id
        slash = _SLASH_REPLY_RE.match(text)
        if slash:
            return "reply", (slash.group(1), slash.group(2).strip())

        # Reply-to-message with an [esc:id] tag in the original → reply
        reply_to = message.get("reply_to_message") or {}
        original_text = reply_to.get("text", "")
        tag = _ESC_TAG_RE.search(original_text)
        if tag:
            return "reply", (tag.group(1), text)

        # Everything else is a free-form chat message from the operator
        return "chat", text

    async def _process_updates(self, updates: list[dict]) -> None:
        max_update_id = 0
        for update in updates:
            max_update_id = max(max_update_id, int(update.get("update_id", 0)))
            message = update.get("message") or {}
            chat = message.get("chat") or {}
            chat_id = chat.get("id")
            # Authentication: silently ignore anyone who isn't the configured operator.
            if chat_id != self._chat_id_int:
                logger.warning(
                    "Telegram message from unauthorised chat_id=%s — ignoring", chat_id,
                )
                continue
            classified = self._classify_message(message)
            if not classified:
                continue
            kind, payload = classified
            if kind == "reply":
                esc_id, reply_text = payload  # type: ignore[misc]
                await self._append_reply(esc_id, reply_text)
                logger.info("Telegram reply for %s: %s", esc_id, reply_text[:120])
            elif kind == "chat":
                await self._append_chat(payload)  # type: ignore[arg-type]
                logger.info("Telegram chat from operator: %s", str(payload)[:120])
        if max_update_id:
            # Telegram protocol: next offset = highest update_id seen + 1
            self._save_offset(max_update_id + 1)

    async def _append_reply(self, escalation_id: str, reply_text: str) -> None:
        from clawbot.escalation import write_operator_reply
        await write_operator_reply(self._metrics_dir, escalation_id, reply_text)

    async def _append_chat(self, text: str) -> None:
        from clawbot.chat import append_operator_message
        await append_operator_message(self._metrics_dir, text)

    async def poll_forever(self) -> None:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_S) as client:
            while True:
                updates = await self._fetch_updates(client)
                if updates:
                    await self._process_updates(updates)


def _html_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
