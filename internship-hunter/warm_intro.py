"""Warm-intro pipeline: UCL alumni at target companies → intro-request DMs.

The single highest-leverage move in the outreach plan. Cold-email replies
run at ~3%. Warm intros via a UCL alumni handoff at the same companies
reply at ~30%. Same target, ten times the yield.

This module does NOT scrape LinkedIn — that breaks ToS and gets accounts
banned. Harry identifies alumni manually (LinkedIn search "people at
<company>" filtered by UCL education), enters them with the CLI, and the
generator emits the alum-facing DM. Status transitions are tracked in
SQLite so the funnel is visible.

Status flow:
    identified  → requested  → (accepted | declined) → intro_sent

CLI:
    python warm_intro.py add Sarah Smith Volt --alum-role "Engineering Lead"
    python warm_intro.py generate 1
    python warm_intro.py status 1 requested
    python warm_intro.py list --status identified
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass

import anthropic
from anthropic.types import TextBlock

from config import ANTHROPIC_API_KEY, GENERATE_MODEL, PROFILE_PATH
from tracker import get_conn

__all__ = [
    "ALLOWED_STATUSES",
    "WarmIntro",
    "add_alum",
    "ensure_schema",
    "generate_intro_request",
    "get_intro",
    "list_intros",
    "mark_status",
]


log = logging.getLogger(__name__)


ALLOWED_STATUSES: tuple[str, ...] = (
    "identified",   # alum spotted, not yet contacted
    "requested",    # Harry sent the intro-request DM
    "accepted",     # alum agreed to make the intro
    "declined",     # alum declined or didn't respond within 7 days
    "intro_sent",   # alum forwarded Harry's pitch to the target
)


@dataclass
class WarmIntro:
    id: int
    alum_first: str
    alum_last: str
    alum_role: str
    alum_context: str
    target_company: str
    target_first: str
    target_last: str
    target_role: str
    status: str
    created: str
    notes: str = ""


# ── Schema ────────────────────────────────────────────────────────────────────


_SCHEMA = """
CREATE TABLE IF NOT EXISTS warm_intros (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    alum_first      TEXT NOT NULL,
    alum_last       TEXT NOT NULL,
    alum_role       TEXT DEFAULT '',
    alum_context    TEXT DEFAULT '',
    target_company  TEXT NOT NULL,
    target_first    TEXT DEFAULT '',
    target_last     TEXT DEFAULT '',
    target_role     TEXT DEFAULT '',
    status          TEXT DEFAULT 'identified',
    created         TEXT DEFAULT (datetime('now')),
    notes           TEXT DEFAULT ''
)
"""


def ensure_schema() -> None:
    """Create the warm_intros table if it doesn't exist. Idempotent."""
    with get_conn() as conn:
        conn.execute(_SCHEMA)


# ── CRUD ─────────────────────────────────────────────────────────────────────


def add_alum(
    alum_first: str,
    alum_last: str,
    target_company: str,
    *,
    alum_role: str = "",
    alum_context: str = "",
    target_first: str = "",
    target_last: str = "",
    target_role: str = "",
    notes: str = "",
) -> int:
    """Register a UCL alum at a target company. Returns the new row id."""
    ensure_schema()
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO warm_intros"
            " (alum_first, alum_last, alum_role, alum_context, target_company,"
            "  target_first, target_last, target_role, notes)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (
                alum_first, alum_last, alum_role, alum_context, target_company,
                target_first, target_last, target_role, notes,
            ),
        )
        new_id = cur.lastrowid
        if new_id is None:
            raise RuntimeError(
                f"sqlite did not return a rowid for warm-intro insert "
                f"({alum_first} {alum_last} @ {target_company})"
            )
        return new_id


def mark_status(intro_id: int, new_status: str) -> None:
    """Transition a warm-intro row. Raises on unknown status."""
    if new_status not in ALLOWED_STATUSES:
        raise ValueError(
            f"Unknown status: {new_status!r}. Allowed: {', '.join(ALLOWED_STATUSES)}"
        )
    ensure_schema()
    with get_conn() as conn:
        conn.execute(
            "UPDATE warm_intros SET status=? WHERE id=?",
            (new_status, intro_id),
        )


def get_intro(intro_id: int) -> WarmIntro | None:
    ensure_schema()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM warm_intros WHERE id=?", (intro_id,)
        ).fetchone()
        return WarmIntro(**dict(row)) if row else None


def list_intros(status: str | None = None) -> list[WarmIntro]:
    ensure_schema()
    with get_conn() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM warm_intros WHERE status=? ORDER BY created DESC",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM warm_intros ORDER BY created DESC"
            ).fetchall()
        return [WarmIntro(**dict(r)) for r in rows]


# ── Generator ────────────────────────────────────────────────────────────────


_INTRO_REQUEST_SYSTEM_TEMPLATE = """You write short LinkedIn DMs from Harry Winter (UCL undergraduate, summer 2026 data/analyst/ML internship search) to UCL alumni asking for an intro to someone at the alum's current company.

NON-NEGOTIABLES:

Length: 60–90 words.

Tone: warm but not fawning. Same school = shared context, NOT a personal friendship. Don't gush. Don't apologise for reaching out.

Structure:
- Sentence 1: open with the UCL connection naturally. e.g. "Saw on LinkedIn we both did IMB at UCL" or "Came across your profile, fellow UCL grad."
- Sentence 2: one line on what Harry is doing now (penultimate year, summer 2026 search) and the single most relevant credential tied to what the alum's company does.
- Sentence 3-4: the specific ask. Name the target person or team. "Would you be open to passing on a short note from me to [target_first] / the [team] team?" Keep it low-friction.
- Sentence 5: explicit out — "Totally understand if not, appreciate the consideration either way."

Banned:
- "I hope this finds you well" / "fast-paced" / "I am passionate about" / "I would love to" / "exciting opportunity"
- Em-dashes anywhere. Use periods or commas.
- Quant jargon (NSGA-III, PPO, DSR, PBO, CPCV).
- Begging language ("any chance", "even just a quick look").

Sign-off: do NOT write "Hi X" at the start or "— Harry" at the end. The sender attaches those. Output ONLY the body sentences.

HARRY'S PROFILE:
{profile}
"""


_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        if not ANTHROPIC_API_KEY:
            raise ValueError(
                "ANTHROPIC_API_KEY not set — required to generate intro requests."
            )
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def generate_intro_request(
    alum_first: str,
    alum_role: str,
    alum_context: str,
    target_company: str,
    target_first: str = "",
    target_role: str = "data / analyst / ML internship",
    *,
    client: anthropic.Anthropic | None = None,
) -> tuple[str, dict[str, int]]:
    """Generate the alum-facing DM body. Returns (message_body, usage)."""
    profile = PROFILE_PATH.read_text(encoding="utf-8")
    system_prompt = _INTRO_REQUEST_SYSTEM_TEMPLATE.format(profile=profile)

    target_who = target_first or f"someone on the {target_role} team"
    user_message = (
        f"Write the intro-request DM body for:\n\n"
        f"UCL alum: {alum_first}, role: {alum_role or '(unknown)'} at {target_company}\n"
        f"What the alum does: {alum_context or '(unknown)'}\n\n"
        f"Who Harry wants reached at {target_company}: {target_who}\n"
        f"Why: {target_role}\n\n"
        "Output ONLY the message body."
    )

    active = client or _get_client()
    response = active.messages.create(
        model=GENERATE_MODEL,
        max_tokens=350,
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


# ── CLI ──────────────────────────────────────────────────────────────────────


def _cmd_add(args: argparse.Namespace) -> int:
    new_id = add_alum(
        args.alum_first, args.alum_last, args.target_company,
        alum_role=args.alum_role, alum_context=args.alum_context,
        target_first=args.target_first, target_role=args.target_role,
    )
    print(f"Added warm_intro #{new_id}: {args.alum_first} {args.alum_last} @ {args.target_company}")
    return 0


def _cmd_generate(args: argparse.Namespace) -> int:
    intro = get_intro(args.intro_id)
    if intro is None:
        print(f"No warm_intro with id {args.intro_id}", file=sys.stderr)
        return 1
    message, _usage = generate_intro_request(
        alum_first=intro.alum_first,
        alum_role=intro.alum_role,
        alum_context=intro.alum_context,
        target_company=intro.target_company,
        target_first=intro.target_first,
        target_role=intro.target_role or "data / analyst / ML internship",
    )
    print(f"=== Intro request to {intro.alum_first} {intro.alum_last} ({intro.target_company}) ===\n")
    print(message)
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    mark_status(args.intro_id, args.new_status)
    print(f"#{args.intro_id} → {args.new_status}")
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    intros = list_intros(args.status)
    if not intros:
        print("(none)")
        return 0
    for i in intros:
        target = f"{i.target_first} {i.target_last}".strip() or i.target_role or "—"
        print(
            f"#{i.id:3d}  [{i.status:10s}]  "
            f"{i.alum_first} {i.alum_last:15s}  @ {i.target_company:20s}  → {target}"
        )
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="warm_intro",
        description="UCL-alumni warm-intro pipeline. Manual entry, Claude-generated DM.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    add_p = sub.add_parser("add", help="Register a UCL alum at a target company.")
    add_p.add_argument("alum_first")
    add_p.add_argument("alum_last")
    add_p.add_argument("target_company")
    add_p.add_argument("--alum-role",    default="", help="alum's job title at target_company")
    add_p.add_argument("--alum-context", default="", help="what the alum does day-to-day")
    add_p.add_argument("--target-first", default="", help="contact Harry wants reached")
    add_p.add_argument("--target-role",  default="data / analyst / ML internship")
    add_p.set_defaults(func=_cmd_add)

    gen_p = sub.add_parser("generate", help="Generate the intro-request DM body.")
    gen_p.add_argument("intro_id", type=int)
    gen_p.set_defaults(func=_cmd_generate)

    status_p = sub.add_parser("status", help="Update an intro's status.")
    status_p.add_argument("intro_id", type=int)
    status_p.add_argument("new_status", choices=ALLOWED_STATUSES)
    status_p.set_defaults(func=_cmd_status)

    list_p = sub.add_parser("list", help="List intros, optionally filtered by status.")
    list_p.add_argument("--status", choices=ALLOWED_STATUSES, default=None)
    list_p.set_defaults(func=_cmd_list)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
