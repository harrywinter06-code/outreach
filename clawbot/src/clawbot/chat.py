"""
Operator chat — free-form conversation between the operator and the agents.

How it differs from escalations:
- Escalation: agent-initiated → operator (one-way request, optional reply).
- Chat: operator-initiated → CEO → operator (two-way, conversational).

Flow:
1. Operator types any message in Telegram (no /reply prefix, no reply-to).
2. TelegramReceiver classifies it as `chat` and calls `append_operator_message`.
3. Scheduler `_chat_responder_loop` drains new messages from
   /metrics/operator_inbox.jsonl, generates a CEO response, sends it back
   through the escalation channel so it surfaces in Telegram naturally.
4. The CEO sees the operator's message in its next executive cycle too (the
   inbox is also pushed to the `operator.message` bus topic) so multi-cycle
   context accumulates.

Offset persistence prevents replays on scheduler restart, same pattern as the
reply store. Each chat round-trip costs ~1 executive-tier LLM call.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, UTC
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from clawbot.company_brain import CompanyBrain
    from clawbot.llm_pool import LLMPool

logger = logging.getLogger(__name__)

OPERATOR_MESSAGE_TOPIC = "operator.message"
INBOX_FILENAME = "operator_inbox.jsonl"
OFFSET_FILENAME = "operator_inbox.offset"


@dataclass(frozen=True)
class OperatorMessage:
    ts: str
    text: str


async def append_operator_message(metrics_dir: Path, text: str) -> None:
    """Add a free-form operator message to the inbox JSONL. Caller is whoever
    received the message (TelegramReceiver today; could be a web UI tomorrow)."""
    metrics_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now(UTC).isoformat(),
        "text": str(text)[:4000],
    }
    path = metrics_dir / INBOX_FILENAME
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


class OperatorInbox:
    """Append-only JSONL with offset-based draining. Idempotent across restarts."""

    def __init__(self, metrics_dir: Path) -> None:
        self._metrics_dir = metrics_dir

    def _inbox_path(self) -> Path:
        return self._metrics_dir / INBOX_FILENAME

    def _offset_path(self) -> Path:
        return self._metrics_dir / OFFSET_FILENAME

    def _load_offset(self) -> int:
        try:
            return int(self._offset_path().read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return 0

    def _save_offset(self, offset: int) -> None:
        try:
            self._offset_path().write_text(str(offset), encoding="utf-8")
        except OSError as exc:
            logger.warning("Could not persist inbox offset: %s", exc)

    def drain_new_messages(self) -> list[OperatorMessage]:
        path = self._inbox_path()
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").splitlines()
        last_offset = self._load_offset()
        new_lines = lines[last_offset:]
        out: list[OperatorMessage] = []
        for line in new_lines:
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                out.append(OperatorMessage(
                    ts=str(data.get("ts", "")),
                    text=str(data.get("text", ""))[:4000],
                ))
            except (json.JSONDecodeError, TypeError):
                continue
        self._save_offset(len(lines))
        return out


CHAT_SYSTEM_TAIL = """\

You are the CEO talking directly to the human operator over Telegram chat.
Conversational register:
- Lowercase opener acceptable. No corporate headers.
- Reply like you'd text a co-founder, not like a sysadmin alert.
- Brief by default — 1-4 sentences unless they ask for depth.
- If the question is operational (numbers / status / decisions), answer with the
  specific number or decision first, then ≤1 sentence of context.
- If you genuinely don't know, say so. Don't fabricate metrics or revenue.
- If their question implies a strategic shift, flag the trade-off in one
  sentence — don't unilaterally commit.

You may use 1 emoji at most. No bullet lists for short answers.
"""


async def respond_to_operator(
    pool: "LLMPool",
    agents_dir: Path,
    metrics_dir: Path,
    message_text: str,
    brain: "CompanyBrain | None" = None,
) -> str:
    """Generate a casual CEO response to an operator message. Returns the
    response text. Caller decides how to deliver it (Telegram, escalation, etc)."""
    ceo_soul_path = agents_dir / "ceo" / "SOUL.md"
    soul = ceo_soul_path.read_text(encoding="utf-8") if ceo_soul_path.exists() else ""

    metrics_summary = _load_metrics_summary(metrics_dir)
    brain_context = await _recent_decisions(brain, message_text)

    messages = [
        {"role": "system", "content": soul + CHAT_SYSTEM_TAIL},
        {
            "role": "user",
            "content": (
                f"[operator message]\n{message_text}\n\n"
                f"[current company snapshot]\n{metrics_summary}"
                f"{brain_context}"
            ),
        },
    ]
    try:
        response = await pool.complete(messages, tier="executive", temperature=0.5, max_tokens=600)
    except Exception as exc:
        logger.warning("Chat response failed: %s", exc)
        return ""
    return response.strip()


def _load_metrics_summary(metrics_dir: Path) -> str:
    """Compact snapshot of company state for the chat context."""
    path = metrics_dir / "company_metrics.json"
    if not path.exists():
        return "(no metrics yet — system just booted)"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "(metrics file unreadable)"
    return (
        f"7-day revenue: £{data.get('revenue_7d_gbp', 0):.2f}\n"
        f"workers: {data.get('worker_count', 0)}\n"
        f"updated: {data.get('timestamp', '?')}"
    )


async def _recent_decisions(brain: "CompanyBrain | None", message_text: str) -> str:
    """Pull 3 most-relevant prior decisions if brain is available and message
    is substantive enough for embedding similarity to mean anything."""
    if brain is None or len(message_text) < 20:
        return ""
    try:
        entries = await brain.search(query=message_text[:500], k=3, category="decision")
    except Exception as exc:
        logger.warning("Brain recall during chat failed: %s", exc)
        return ""
    if not entries:
        return ""
    return "\n\n[relevant prior decisions]\n" + "\n".join(
        f"- {e.content[:200]}" for e in entries
    )
