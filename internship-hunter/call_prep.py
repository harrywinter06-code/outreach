"""Reply pipeline + automatic call-prep memo.

The system previously ended at "email sent". This module covers the next
two steps:

  1. log_reply(queue_id, reply_text) — mark an email as replied-to,
     surfacing it in the dashboard.
  2. generate_call_prep_memo(...) — auto-produces a structured memo Harry
     reads before his initial call:
        - About the company (concrete, not "innovative")
        - This person's likely angle on the conversation
        - Three specific questions to ask
        - The 60-second story Harry should tell
        - What to send within 24 h after the call

A great first call lifts P(offer | reply) by 30-50% over an average call.
Most of that lift is preparation. This module makes the prep mechanical.

Schema additions to email_queue (idempotent, run on import):
    replied      INTEGER DEFAULT 0
    replied_at   TEXT
    reply_text   TEXT
    prep_memo    TEXT
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

import anthropic
from anthropic.types import TextBlock

from config import ANTHROPIC_API_KEY, GENERATE_MODEL, PROFILE_PATH
from tracker import get_conn

__all__ = [
    "CallPrep",
    "ensure_schema",
    "generate_call_prep_memo",
    "get_pending_calls",
    "log_reply",
    "save_prep_memo",
]


log = logging.getLogger(__name__)


@dataclass
class CallPrep:
    queue_id: int
    company: str
    contact_name: str
    contact_email: str
    original_subject: str
    original_body: str
    reply_text: str
    replied_at: str
    prep_memo: str = ""


# ── Schema (additive columns) ────────────────────────────────────────────────


_NEW_COLUMNS: list[tuple[str, str]] = [
    ("replied",    "INTEGER DEFAULT 0"),
    ("replied_at", "TEXT"),
    ("reply_text", "TEXT"),
    ("prep_memo",  "TEXT"),
]


def _existing_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def ensure_schema() -> None:
    """Add the reply-tracking columns to email_queue if missing. Idempotent."""
    with get_conn() as conn:
        existing = _existing_columns(conn, "email_queue")
        for column, ddl in _NEW_COLUMNS:
            if column not in existing:
                conn.execute(f"ALTER TABLE email_queue ADD COLUMN {column} {ddl}")


# ── Reply logging ────────────────────────────────────────────────────────────


def log_reply(queue_id: int, reply_text: str) -> None:
    """Mark an email as replied-to. Stores the reply text for later memo generation."""
    if not reply_text.strip():
        raise ValueError("reply_text is required — store the actual message body.")
    ensure_schema()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM email_queue WHERE id=?", (queue_id,)
        ).fetchone()
        if not row:
            raise ValueError(f"No email_queue row with id={queue_id}")
        conn.execute(
            "UPDATE email_queue SET replied=1, replied_at=datetime('now'), reply_text=?"
            " WHERE id=?",
            (reply_text, queue_id),
        )
    log.info("Logged reply on queue_id=%s", queue_id)


def save_prep_memo(queue_id: int, memo: str) -> None:
    """Persist a generated memo onto the email_queue row."""
    ensure_schema()
    with get_conn() as conn:
        conn.execute(
            "UPDATE email_queue SET prep_memo=? WHERE id=?",
            (memo, queue_id),
        )


def get_pending_calls() -> list[CallPrep]:
    """Replies received but no memo yet generated."""
    ensure_schema()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, company, contact_name, contact_email, subject, body,"
            " reply_text, replied_at, prep_memo"
            " FROM email_queue"
            " WHERE replied=1 AND (prep_memo IS NULL OR prep_memo='')"
            " ORDER BY replied_at DESC"
        ).fetchall()
    return [
        CallPrep(
            queue_id=int(r["id"]),
            company=r["company"] or "",
            contact_name=r["contact_name"] or "",
            contact_email=r["contact_email"] or "",
            original_subject=r["subject"] or "",
            original_body=r["body"] or "",
            reply_text=r["reply_text"] or "",
            replied_at=r["replied_at"] or "",
            prep_memo=r["prep_memo"] or "",
        )
        for r in rows
    ]


# ── Memo generator ───────────────────────────────────────────────────────────


_MEMO_SYSTEM_TEMPLATE = """You write call-prep memos for Harry Winter (UCL undergraduate, summer 2026 data/analyst/ML internship search) before his first call with a founder or hiring lead who replied to a cold email.

The memo is internal. Harry reads it to prepare, then deletes it.

OUTPUT EXACTLY THIS STRUCTURE — no extra prose, no preamble, no closing line:

## About this company
2-3 sentences. Concrete: what they actually do, who they sell to, their stage. Inferable from the original email + reply. If the reply suggests they're hiring for a specific problem, name it. No "innovative", no "exciting".

## This person's likely angle
1-2 sentences. Why they replied. What they probably want to learn in 15 minutes. What would have to be true for them to push Harry toward a yes.

## Three questions to ask
Three questions, numbered. Each one targeted: it should reveal information that helps Harry decide if the role is a fit AND signal to the founder that Harry is thinking like a hire, not a candidate.

## The 60-second story
Three sentences Harry should be ready to recite if asked "tell me about yourself". Hook → relevant credential tied to THEIR work → why he specifically wants to work with them. Honest about what he has and hasn't done. No algorithm names or quant jargon (NSGA-III, PPO, DSR, PBO, CPCV).

## Within 24 hours after the call
A 2-sentence template Harry can paste into a follow-up email after the call. Reference one specific thing the founder said. Confirm next step. No fluff.

RULES:
- No em-dashes anywhere. Use periods or commas.
- No banned phrases: "I am passionate about", "I would love to", "exciting opportunity", "fast-paced".
- Every claim Harry might say must be defensible — he built a Python trading pipeline and a job-outreach tool. He has not deployed real-money capital. He has not published research.

HARRY'S PROFILE (truth source):
{profile}
"""


_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        if not ANTHROPIC_API_KEY:
            raise ValueError(
                "ANTHROPIC_API_KEY not set — required to generate call-prep memos."
            )
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def generate_call_prep_memo(
    company: str,
    contact_name: str,
    original_subject: str,
    original_body: str,
    reply_text: str,
    *,
    client: anthropic.Anthropic | None = None,
) -> tuple[str, dict[str, int]]:
    """Produce a structured pre-call memo. Returns (memo_markdown, usage)."""
    if not reply_text.strip():
        raise ValueError("reply_text is required — memo needs the actual reply.")

    profile = PROFILE_PATH.read_text(encoding="utf-8")
    system_prompt = _MEMO_SYSTEM_TEMPLATE.format(profile=profile)

    user_message = (
        f"Generate the call-prep memo.\n\n"
        f"Company: {company}\n"
        f"Contact: {contact_name}\n\n"
        f"Original email Harry sent\n"
        f"Subject: {original_subject}\n"
        f"---\n{original_body}\n\n"
        f"Their reply\n---\n{reply_text}\n\n"
        "Output the memo in the exact structure specified."
    )

    active = client or _get_client()
    response = active.messages.create(
        model=GENERATE_MODEL,
        max_tokens=900,
        system=[{
            "type": "text",
            "text": system_prompt,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": user_message}],
    )
    text = next((b.text for b in response.content if isinstance(b, TextBlock)), "")
    usage = {
        "input_tokens":  int(response.usage.input_tokens),
        "output_tokens": int(response.usage.output_tokens),
        "cache_read":    int(getattr(response.usage, "cache_read_input_tokens", 0) or 0),
        "cache_write":   int(getattr(response.usage, "cache_creation_input_tokens", 0) or 0),
    }
    return text.strip(), usage


def generate_and_save_memo_for(queue_id: int) -> str:
    """Pull the row, generate the memo, persist it, and return the markdown."""
    ensure_schema()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT company, contact_name, subject, body, reply_text"
            " FROM email_queue WHERE id=? AND replied=1",
            (queue_id,),
        ).fetchone()
    if row is None:
        raise ValueError(f"No replied email with id={queue_id}")

    memo, _usage = generate_call_prep_memo(
        company=row["company"] or "",
        contact_name=row["contact_name"] or "",
        original_subject=row["subject"] or "",
        original_body=row["body"] or "",
        reply_text=row["reply_text"] or "",
    )
    save_prep_memo(queue_id, memo)
    return memo
