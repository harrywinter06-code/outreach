#!/usr/bin/env python
"""Operator CLI: view escalations + reply to them.

Usage (run from inside the container, or with the metrics volume mounted):
    python scripts/escalations.py list                  # show recent escalations
    python scripts/escalations.py list --limit 10
    python scripts/escalations.py show <id>             # full detail for one
    python scripts/escalations.py reply <id> "your text"  # send a reply

The scheduler picks up replies from /metrics/escalation_replies.jsonl and
publishes them to the operator.reply bus topic. Any agent that escalated with
a correlation_id can subscribe and match.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Resolve metrics dir — env override beats default
import os
METRICS_DIR = Path(os.environ.get("METRICS_DIR", "/metrics"))


def _load_log(limit: int) -> list[dict]:
    log_path = METRICS_DIR / "escalations.jsonl"
    if not log_path.exists():
        return []
    lines = log_path.read_text(encoding="utf-8").splitlines()
    out: list[dict] = []
    for line in lines[-limit:]:
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def cmd_list(args: argparse.Namespace) -> int:
    entries = _load_log(args.limit)
    if not entries:
        print("No escalations yet.")
        return 0
    print(f"{'ID':<14} {'TIME':<26} {'SEV':<8} {'FROM':<12} SUMMARY")
    for e in entries:
        ts = e.get("ts", "")[:25]
        print(f"{e.get('id', ''):<14} {ts:<26} {e.get('severity', ''):<8} "
              f"{e.get('from_agent', ''):<12} {e.get('summary', '')[:80]}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    detail_path = METRICS_DIR / "escalations" / f"{args.id}.json"
    if not detail_path.exists():
        print(f"No escalation with id={args.id}", file=sys.stderr)
        return 1
    print(detail_path.read_text(encoding="utf-8"))
    return 0


def cmd_reply(args: argparse.Namespace) -> int:
    from clawbot.escalation import write_operator_reply
    asyncio.run(write_operator_reply(METRICS_DIR, args.id, args.text))
    print(f"Reply queued for {args.id}. Scheduler will publish on the next poll (~60s).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Clawbot operator escalation CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    list_p = sub.add_parser("list", help="Show recent escalations")
    list_p.add_argument("--limit", type=int, default=20)
    list_p.set_defaults(func=cmd_list)

    show_p = sub.add_parser("show", help="Full detail for one escalation")
    show_p.add_argument("id")
    show_p.set_defaults(func=cmd_show)

    reply_p = sub.add_parser("reply", help="Reply to an escalation")
    reply_p.add_argument("id")
    reply_p.add_argument("text")
    reply_p.set_defaults(func=cmd_reply)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
