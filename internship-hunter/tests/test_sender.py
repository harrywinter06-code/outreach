"""SMTP sender contract.

We mock smtplib.SMTP_SSL at the system boundary and assert on what the
sender does with the returned context manager.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import sender
import tracker


@pytest.fixture(autouse=True)
def _wipe_email_queue() -> None:
    """Each sender test starts from an empty queue.

    The DB is shared across the session (single tmp file) so we explicitly
    reset the table the sender reads from rather than rely on test order.
    """
    with tracker.get_conn() as conn:
        conn.execute("DELETE FROM email_queue")


@pytest.fixture
def configure_gmail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sender, "GMAIL_ADDRESS", "test@example.com")
    monkeypatch.setattr(sender, "GMAIL_APP_PASSWORD", "fake-app-password")


def _make_fake_smtp() -> tuple[MagicMock, MagicMock]:
    smtp_instance = MagicMock(name="smtp_instance")
    smtp_ctor = MagicMock(name="smtp_ctor")
    smtp_ctor.return_value.__enter__.return_value = smtp_instance
    smtp_ctor.return_value.__exit__.return_value = False
    return smtp_ctor, smtp_instance


def test_send_one_logs_in_and_calls_sendmail(configure_gmail: None) -> None:
    smtp_ctor, smtp_instance = _make_fake_smtp()
    with patch("sender.smtplib.SMTP_SSL", smtp_ctor):
        ok = sender.send_one("alice@target.test", "subject", "body")
    assert ok is True
    smtp_instance.login.assert_called_once_with("test@example.com", "fake-app-password")
    smtp_instance.sendmail.assert_called_once()
    args = smtp_instance.sendmail.call_args.args
    assert args[0] == "test@example.com"
    assert args[1] == "alice@target.test"
    assert "Subject: subject" in args[2]


def test_send_one_marks_queue_id_sent_on_success(configure_gmail: None) -> None:
    queue_id = tracker.queue_email(
        company="MarkSentCo",
        contact_name="Bob",
        contact_email="bob@marksent.test",
        subject="hi", body="body",
    )

    smtp_ctor, _ = _make_fake_smtp()
    with patch("sender.smtplib.SMTP_SSL", smtp_ctor):
        sender.send_one("bob@marksent.test", "hi", "body", queue_id=queue_id)

    row = next(q for q in tracker.get_email_queue() if q["id"] == queue_id)
    assert row["status"] == "sent"
    assert row["sent_at"] is not None


def test_send_one_raises_when_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sender, "GMAIL_ADDRESS", "")
    monkeypatch.setattr(sender, "GMAIL_APP_PASSWORD", "")
    with pytest.raises(sender.SendError):
        sender.send_one("x@y.test", "s", "b")


def test_send_approved_batch_respects_daily_limit(
    configure_gmail: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sender, "EMAIL_DAILY_MAX", 2)
    monkeypatch.setattr(sender, "EMAIL_SEND_DELAY_SECONDS", 0)
    monkeypatch.setattr(sender, "_sent_today", lambda: 0)

    queued_ids = []
    for i in range(5):
        qid = tracker.queue_email(
            company=f"BatchCo{i}",
            contact_name="Anon",
            contact_email=f"u{i}@batch.test",
            subject=f"s{i}", body="b",
        )
        tracker.approve_email(qid)
        queued_ids.append(qid)

    smtp_ctor, _ = _make_fake_smtp()
    with patch("sender.smtplib.SMTP_SSL", smtp_ctor):
        result = sender.send_approved_batch()

    assert result["sent"] == 2
    assert result["skipped_daily_limit"] == 3
    assert result["failed"] == 0


def test_send_approved_batch_records_failures(
    configure_gmail: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sender, "EMAIL_DAILY_MAX", 10)
    monkeypatch.setattr(sender, "EMAIL_SEND_DELAY_SECONDS", 0)
    monkeypatch.setattr(sender, "_sent_today", lambda: 0)

    qid = tracker.queue_email(
        company="FailCo",
        contact_name="Anon",
        contact_email="fail@batch.test",
        subject="s", body="b",
    )
    tracker.approve_email(qid)

    smtp_ctor = MagicMock()
    smtp_ctor.side_effect = OSError("network down")

    errors_seen: list[tuple[int, str, str]] = []

    def _on_error(queue_id: int, company: str, error: str) -> None:
        errors_seen.append((queue_id, company, error))

    with patch("sender.smtplib.SMTP_SSL", smtp_ctor):
        result = sender.send_approved_batch(on_error=_on_error)

    assert result["sent"] == 0
    assert result["failed"] == 1
    assert errors_seen and errors_seen[0][1] == "FailCo"

    row = next(q for q in tracker.get_email_queue() if q["id"] == qid)
    assert row["status"] == "failed"
    assert row["error"] is not None
