"""
Operator escalation channel — the way any agent gets a human in the loop.

Flow:
1. Agent calls `await escalate(bus, severity, summary, detail, from_agent)`.
   Publishes to the `operator.escalation` bus topic.
2. Scheduler `_escalation_subscriber_loop` consumes:
   - Always writes to `/metrics/escalations.jsonl` (one line per escalation).
   - If `NTFY_TOPIC` is set, also pushes to ntfy.sh (free, no auth — operator
     subscribes via the ntfy phone app or browser).
3. Operator replies (optional) by appending to `/metrics/escalation_replies.jsonl`:
       {"id": "<escalation-id>", "reply": "<text>"}
   The scheduler's `_operator_reply_loop` picks it up and publishes to
   `operator.reply` bus topic. Any agent waiting on a reply can subscribe.

Severity levels:
- info: low-priority (FYI, no action needed)
- request: agent needs the operator to do something (PDF upload, account creation)
- warning: something is off but not catastrophic
- urgent: kill-switch territory — operator should look immediately

Persistence-first: if ntfy push fails (network, downtime, wrong topic) the
escalation is still on disk. Operator can ssh in or check the bind-mounted
metrics directory.
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, UTC
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import httpx

if TYPE_CHECKING:
    from clawbot.bus import MessageBus

logger = logging.getLogger(__name__)

ESCALATION_TOPIC = "operator.escalation"
REPLY_TOPIC = "operator.reply"
NTFY_TIMEOUT_S = 5.0

Severity = Literal["info", "request", "warning", "urgent"]
_NTFY_PRIORITY = {"info": "low", "request": "default", "warning": "high", "urgent": "urgent"}
_NTFY_TAGS = {
    "info": "information_source",
    "request": "hand",
    "warning": "warning",
    "urgent": "rotating_light",
}


@dataclass(frozen=True)
class Escalation:
    id: str
    ts: str
    severity: Severity
    from_agent: str
    summary: str
    detail: str
    correlation_id: str = ""  # optional — agents can use this to match replies

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class OperatorReply:
    escalation_id: str
    ts: str
    reply: str


async def escalate(
    bus: "MessageBus",
    severity: Severity,
    summary: str,
    detail: str,
    from_agent: str,
    correlation_id: str = "",
) -> Escalation:
    """Agent-facing entry point. Returns the Escalation that was published.

    Callers can keep the `id` if they want to match a later reply via the
    `operator.reply` bus topic — the reply's `escalation_id` field will match.
    """
    esc = Escalation(
        id=uuid.uuid4().hex[:12],
        ts=datetime.now(UTC).isoformat(),
        severity=severity,
        from_agent=from_agent,
        summary=summary[:300],
        detail=detail[:4000],
        correlation_id=correlation_id,
    )
    await bus.publish(ESCALATION_TOPIC, esc.to_dict())
    return esc


class EscalationStore:
    """Disk persistence + optional ntfy.sh push + optional Telegram push.
    Always persists first; push channels run independently and never block
    each other."""

    def __init__(
        self,
        metrics_dir: Path,
        ntfy_topic: str = "",
        ntfy_base_url: str = "https://ntfy.sh",
        telegram_sender: "object | None" = None,
    ) -> None:
        self._metrics_dir = metrics_dir
        self._ntfy_topic = ntfy_topic.strip()
        self._ntfy_base_url = ntfy_base_url.rstrip("/")
        self._telegram = telegram_sender  # TelegramSender, typed loosely to avoid import cycle

    def _log_path(self) -> Path:
        return self._metrics_dir / "escalations.jsonl"

    def _detail_path(self, escalation_id: str) -> Path:
        return self._metrics_dir / "escalations" / f"{escalation_id}.json"

    def persist(self, esc: Escalation) -> None:
        """Append to the JSONL log AND drop a per-escalation JSON file with full detail.
        JSONL is the at-a-glance feed; per-escalation files preserve long detail
        without bloating the feed."""
        self._metrics_dir.mkdir(parents=True, exist_ok=True)
        (self._metrics_dir / "escalations").mkdir(exist_ok=True)
        try:
            with self._log_path().open("a", encoding="utf-8") as f:
                f.write(json.dumps(esc.to_dict()) + "\n")
            self._detail_path(esc.id).write_text(
                json.dumps(esc.to_dict(), indent=2), encoding="utf-8"
            )
        except OSError as exc:
            logger.error("Escalation persist failed for %s: %s", esc.id, exc)

    async def push_ntfy(self, esc: Escalation) -> bool:
        """Fire-and-forget ntfy.sh push. Returns True if successful, False otherwise.
        Never raises — push failures must not block the bus consumer."""
        if not self._ntfy_topic:
            return False
        url = f"{self._ntfy_base_url}/{self._ntfy_topic}"
        body = f"[{esc.id}] {esc.summary}\n\n{esc.detail[:500]}"
        try:
            async with httpx.AsyncClient(timeout=NTFY_TIMEOUT_S) as client:
                resp = await client.post(
                    url,
                    content=body.encode("utf-8"),
                    headers={
                        "Title": f"Clawbot {esc.severity}: {esc.from_agent}",
                        "Priority": _NTFY_PRIORITY.get(esc.severity, "default"),
                        "Tags": _NTFY_TAGS.get(esc.severity, "robot"),
                    },
                )
                return 200 <= resp.status_code < 300
        except (httpx.HTTPError, OSError) as exc:
            logger.warning("ntfy push failed for %s: %s (escalation still on disk)", esc.id, exc)
            return False

    async def push_telegram(self, esc: Escalation) -> bool:
        """Fire-and-forget Telegram push via the configured TelegramSender.
        Returns True if sent, False if unconfigured or failed."""
        if self._telegram is None:
            return False
        try:
            msg_id = await self._telegram.send_escalation(esc)  # type: ignore[attr-defined]
            return msg_id is not None
        except Exception as exc:
            logger.warning("Telegram push raised for %s: %s", esc.id, exc)
            return False

    def list_recent(self, limit: int = 50) -> list[Escalation]:
        path = self._log_path()
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").splitlines()
        out: list[Escalation] = []
        for line in lines[-limit:]:
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                out.append(Escalation(**data))
            except (json.JSONDecodeError, TypeError):
                continue
        return out


class ReplyStore:
    """Reads operator replies from /metrics/escalation_replies.jsonl and publishes
    each new one to the bus exactly once.

    Tracks last-processed offset in /metrics/escalation_replies.offset so a
    restart doesn't re-publish all historical replies."""

    def __init__(self, metrics_dir: Path) -> None:
        self._metrics_dir = metrics_dir

    def _replies_path(self) -> Path:
        return self._metrics_dir / "escalation_replies.jsonl"

    def _offset_path(self) -> Path:
        return self._metrics_dir / "escalation_replies.offset"

    def _load_offset(self) -> int:
        try:
            return int(self._offset_path().read_text().strip())
        except (OSError, ValueError):
            return 0

    def _save_offset(self, offset: int) -> None:
        try:
            self._offset_path().write_text(str(offset), encoding="utf-8")
        except OSError as exc:
            logger.warning("Could not save reply offset: %s", exc)

    def drain_new_replies(self) -> list[OperatorReply]:
        """Return replies that have appeared since the last drain. Idempotent."""
        path = self._replies_path()
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").splitlines()
        last_offset = self._load_offset()
        new_lines = lines[last_offset:]
        out: list[OperatorReply] = []
        for line in new_lines:
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                out.append(OperatorReply(
                    escalation_id=str(data.get("id", "")),
                    ts=data.get("ts") or datetime.now(UTC).isoformat(),
                    reply=str(data.get("reply", ""))[:4000],
                ))
            except (json.JSONDecodeError, TypeError):
                continue
        self._save_offset(len(lines))
        return out


async def write_operator_reply(metrics_dir: Path, escalation_id: str, reply_text: str) -> None:
    """Helper for the CLI tool — appends a reply to the JSONL the scheduler reads."""
    path = metrics_dir / "escalation_replies.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "id": escalation_id,
        "ts": datetime.now(UTC).isoformat(),
        "reply": reply_text,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
