"""Tests for the peak-system additions: warm_intro, call_prep, micro_intern.

Database tests share the per-session tmp DB created in conftest.py.
Claude calls are mocked at the SDK boundary — no network, no API key.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from anthropic.types import TextBlock

import call_prep
import micro_intern
import warm_intro
from quality import CheckReport
from tracker import get_conn, queue_email

# ── Helpers ───────────────────────────────────────────────────────────────────


def _fake_client_returning_text(text: str) -> MagicMock:
    """Anthropic-like client whose response.content[0] is a real TextBlock."""
    block = TextBlock(type="text", text=text)
    msg = MagicMock()
    msg.content = [block]
    msg.usage.input_tokens = 100
    msg.usage.output_tokens = 80
    msg.usage.cache_read_input_tokens = 0
    msg.usage.cache_creation_input_tokens = 0

    client = MagicMock()
    client.messages.create.return_value = msg
    return client


# ── warm_intro ───────────────────────────────────────────────────────────────


def test_warm_intro_schema_is_idempotent() -> None:
    warm_intro.ensure_schema()
    warm_intro.ensure_schema()  # double-call shouldn't raise
    with get_conn() as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(warm_intros)").fetchall()}
    expected = {
        "id", "alum_first", "alum_last", "alum_role", "alum_context",
        "target_company", "target_first", "target_last", "target_role",
        "status", "created", "notes",
    }
    assert expected.issubset(cols), f"missing columns: {expected - cols}"


def test_add_alum_round_trip() -> None:
    intro_id = warm_intro.add_alum(
        "Sarah", "Smith", "Volt",
        alum_role="Engineering Lead",
        alum_context="Builds the payment routing engine.",
        target_first="Tom",
        target_role="data / analyst internship",
    )
    assert intro_id > 0
    fetched = warm_intro.get_intro(intro_id)
    assert fetched is not None
    assert fetched.alum_first == "Sarah"
    assert fetched.alum_last == "Smith"
    assert fetched.target_company == "Volt"
    assert fetched.target_first == "Tom"
    assert fetched.status == "identified"


def test_mark_status_transitions() -> None:
    intro_id = warm_intro.add_alum("Alex", "Doe", "Causal")
    warm_intro.mark_status(intro_id, "requested")
    assert (warm_intro.get_intro(intro_id) or MagicMock()).status == "requested"
    warm_intro.mark_status(intro_id, "accepted")
    assert (warm_intro.get_intro(intro_id) or MagicMock()).status == "accepted"


def test_mark_status_rejects_unknown() -> None:
    intro_id = warm_intro.add_alum("Bob", "Roe", "Cleo")
    with pytest.raises(ValueError):
        warm_intro.mark_status(intro_id, "yolo")


def test_list_intros_filters_by_status() -> None:
    a = warm_intro.add_alum("A", "A", "Co1")
    b = warm_intro.add_alum("B", "B", "Co2")
    warm_intro.mark_status(b, "requested")
    ids_requested = {i.id for i in warm_intro.list_intros(status="requested")}
    ids_identified = {i.id for i in warm_intro.list_intros(status="identified")}
    assert b in ids_requested
    assert a in ids_identified
    assert b not in ids_identified


def test_generate_intro_request_calls_claude_and_returns_text() -> None:
    fake = _fake_client_returning_text(
        "Saw you also did IMB at UCL. I'm in my penultimate year and built a Python "
        "trading pipeline that ingests live data daily; hoping to spend summer on a "
        "real data problem. Would you consider passing on a short note to someone "
        "on the data team? Totally understand if not, appreciate it either way."
    )
    message, usage = warm_intro.generate_intro_request(
        alum_first="Sarah",
        alum_role="Engineering Lead",
        alum_context="Builds the routing engine",
        target_company="Volt",
        target_first="Tom",
        client=fake,
    )
    assert message.startswith("Saw")
    assert "UCL" in message
    assert usage["input_tokens"] >= 1
    fake.messages.create.assert_called_once()


# ── call_prep ────────────────────────────────────────────────────────────────


def test_call_prep_adds_reply_columns_idempotently() -> None:
    call_prep.ensure_schema()
    call_prep.ensure_schema()
    with get_conn() as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(email_queue)").fetchall()}
    assert {"replied", "replied_at", "reply_text", "prep_memo"}.issubset(cols)


def test_log_reply_marks_row_and_stores_text() -> None:
    queue_id = queue_email(
        company="ReplyCo",
        contact_name="Alice",
        contact_email="alice@reply.test",
        subject="hi", body="body",
    )
    call_prep.log_reply(queue_id, "Hi Harry — yes happy to chat next Tuesday")
    with get_conn() as conn:
        row = conn.execute(
            "SELECT replied, reply_text, replied_at FROM email_queue WHERE id=?",
            (queue_id,),
        ).fetchone()
    assert row["replied"] == 1
    assert "Tuesday" in row["reply_text"]
    assert row["replied_at"] is not None


def test_log_reply_requires_nonempty_text() -> None:
    queue_id = queue_email(
        company="EmptyReplyCo",
        contact_name="Bob",
        contact_email="bob@empty.test",
        subject="s", body="b",
    )
    with pytest.raises(ValueError):
        call_prep.log_reply(queue_id, "   ")


def test_log_reply_rejects_unknown_queue_id() -> None:
    with pytest.raises(ValueError):
        call_prep.log_reply(999_999, "real reply text")


def test_get_pending_calls_lists_only_replied_without_memo() -> None:
    call_prep.ensure_schema()
    with get_conn() as conn:
        conn.execute("DELETE FROM email_queue")  # isolate this test
    q1 = queue_email("CoA", "X", "x@a.test", "s", "b")
    q2 = queue_email("CoB", "Y", "y@b.test", "s", "b")
    q3 = queue_email("CoC", "Z", "z@c.test", "s", "b")
    call_prep.log_reply(q1, "Reply 1")
    call_prep.log_reply(q2, "Reply 2")
    call_prep.save_prep_memo(q2, "Memo already exists")

    pending = call_prep.get_pending_calls()
    pending_ids = {p.queue_id for p in pending}
    assert q1 in pending_ids
    assert q2 not in pending_ids   # has memo
    assert q3 not in pending_ids   # no reply


def test_generate_call_prep_memo_calls_claude_with_structured_output() -> None:
    sample_memo = (
        "## About this company\nThey build payments infrastructure.\n\n"
        "## This person's likely angle\nWants to assess fit fast.\n\n"
        "## Three questions to ask\n1. What's broken?\n2. Who else?\n3. Timeline?\n\n"
        "## The 60-second story\nUCL, trading pipeline, hoping to apply this.\n\n"
        "## Within 24 hours after the call\nThanks plus next step."
    )
    fake = _fake_client_returning_text(sample_memo)
    memo, usage = call_prep.generate_call_prep_memo(
        company="Volt",
        contact_name="Sarah Smith",
        original_subject="payments routing, ucl student",
        original_body="Hi Sarah,\n\n...",
        reply_text="Hi Harry, happy to chat Tuesday.",
        client=fake,
    )
    assert "About this company" in memo
    assert "Three questions" in memo
    assert usage["output_tokens"] >= 1


def test_generate_call_prep_memo_rejects_empty_reply() -> None:
    with pytest.raises(ValueError):
        call_prep.generate_call_prep_memo(
            company="Co", contact_name="X",
            original_subject="s", original_body="b", reply_text="",
        )


# ── micro_intern ─────────────────────────────────────────────────────────────


_GOOD_MICRO_BODY = (
    "Hi Sarah,\n\n"
    "Volt's open banking payment network handles a serious routing problem, and "
    "the failure-rate numbers on your homepage caught my eye.\n\n"
    "I'm a UCL student in my penultimate year. I built an automated trading "
    "pipeline that ingests live macro and equity data daily with no manual touch. "
    "I'd like to spend the next 7 days analysing public failure-mode data for "
    "cross-border routing and send you a short notebook with what I find. "
    "No expectation of an offer at the end, just useful work if it turns up "
    "anything you don't already see.\n\n"
    "Reply yes if you'd find it useful and I'll start tomorrow.\n\n"
    "- Harry"
)

_GOOD_MICRO_SUBJECT = "routing failure, ucl"


def test_micro_intern_parse_splits_subject_and_body() -> None:
    raw = "Subject: hello world\n---\nHi Sarah,\n\nBody.\n\n- Harry"
    subject, body = micro_intern.parse_micro_intern_output(raw)
    assert subject == "hello world"
    assert body.startswith("Hi Sarah,")


def test_micro_intern_resolves_deliverable_by_sector() -> None:
    from micro_intern import DELIVERABLE_HINTS_BY_SECTOR, _resolve_deliverable
    # Each known sector returns its own seed text (non-empty, non-default).
    for sector, expected in DELIVERABLE_HINTS_BY_SECTOR.items():
        assert _resolve_deliverable(sector, "") == expected
    # Caller-supplied hint always wins.
    assert _resolve_deliverable("anything", "specific custom thing") == "specific custom thing"
    # Unknown sector falls back to a generic seed (not empty).
    assert _resolve_deliverable("not_a_sector", "") != ""


def test_micro_intern_returns_three_tuple_on_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_call(_system: str, _user: str, max_tokens: int = 500) -> tuple[str, dict[str, int]]:
        return (
            f"Subject: {_GOOD_MICRO_SUBJECT}\n---\n{_GOOD_MICRO_BODY}",
            {"input_tokens": 200, "output_tokens": 100, "cache_read": 0, "cache_write": 0},
        )
    monkeypatch.setattr(micro_intern, "_call", _fake_call)

    raw, usage, report = micro_intern.generate_micro_intern_email(
        company="Volt",
        sector="fintech_payments",
        company_context="Open banking payment network across thirty markets.",
        contact_first="Sarah",
        deliverable_hint="failure-rate analysis of cross-border routing decisions",
    )
    assert isinstance(report, CheckReport)
    assert raw.startswith("Subject:")
    assert usage["input_tokens"] >= 200
    assert report.all_passed, report.summary()


def test_micro_intern_regenerates_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bad body first, good body second — verify regen feedback loop."""
    bad_body = "Hi Sarah,\n\nToo short.\n\n- Harry"
    bad = f"Subject: {_GOOD_MICRO_SUBJECT}\n---\n{bad_body}"
    good = f"Subject: {_GOOD_MICRO_SUBJECT}\n---\n{_GOOD_MICRO_BODY}"

    calls: list[int] = []

    def _fake_call(_system: str, _user: str, max_tokens: int = 500) -> tuple[str, dict[str, int]]:
        calls.append(1)
        text = bad if len(calls) == 1 else good
        return text, {"input_tokens": 200, "output_tokens": 100, "cache_read": 0, "cache_write": 0}

    monkeypatch.setattr(micro_intern, "_call", _fake_call)

    raw, usage, report = micro_intern.generate_micro_intern_email(
        company="Volt",
        sector="fintech_payments",
        company_context="Open banking payment network.",
        contact_first="Sarah",
        max_regen_attempts=3,
    )
    assert len(calls) == 2, f"Expected exactly one regen, got {len(calls)} calls"
    assert report.all_passed
    assert usage["input_tokens"] == 400  # both attempts summed


def test_micro_intern_word_budget_wider_than_default() -> None:
    """Direct check on the mechanical wrapper: 100-word body must pass."""
    body_100 = "Hi Sarah,\n\n" + ("word " * 95).strip() + "\n\n- Harry"
    report = micro_intern._check_mechanical_micro(_GOOD_MICRO_SUBJECT, body_100, "Sarah")
    failed = {c.name for c in report.failed()}
    assert "body_word_count" not in failed, (
        "100-word body should pass the wider micro-intern budget"
    )


def test_micro_intern_requires_contact_first() -> None:
    with pytest.raises(ValueError):
        micro_intern.generate_micro_intern_email(
            company="Co", sector="data_analytics",
            company_context="x", contact_first="",
        )
