"""
Gmail SMTP sender.

Uses an App Password — NOT your Gmail login password.
Generate one at: myaccount.google.com → Security → 2-Step Verification → App Passwords

Plain text only. HTML emails from cold addresses have higher spam rates.
Enforces EMAIL_SEND_DELAY_SECONDS between sends and EMAIL_DAILY_MAX per day.
"""

import smtplib
import time
import logging
from datetime import datetime, date
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from config import GMAIL_ADDRESS, GMAIL_APP_PASSWORD, EMAIL_SEND_DELAY_SECONDS, EMAIL_DAILY_MAX
from tracker import get_conn

log = logging.getLogger(__name__)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465


class SendError(Exception):
    pass


def _check_configured():
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        raise SendError(
            "Gmail not configured. Add GMAIL_ADDRESS and GMAIL_APP_PASSWORD to your .env file.\n"
            "Generate an App Password at: myaccount.google.com → Security → 2-Step Verification → App Passwords"
        )


def _sent_today() -> int:
    """Count emails sent today from the queue table."""
    today = date.today().isoformat()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM email_queue WHERE status='sent' AND sent_at LIKE ?",
            (f"{today}%",)
        ).fetchone()
        return row[0] if row else 0


def send_one(to_addr: str, subject: str, body: str, queue_id: int | None = None) -> bool:
    """
    Send a single plain-text email via Gmail SMTP.
    Updates queue_id status in DB if provided.
    Returns True on success, raises SendError on failure.
    """
    _check_configured()

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_ADDRESS
    msg["To"]      = to_addr
    # Plain text — no HTML
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_ADDRESS, to_addr, msg.as_string())
    except smtplib.SMTPAuthenticationError:
        raise SendError("Gmail authentication failed — check your App Password in .env")
    except smtplib.SMTPRecipientsRefused:
        raise SendError(f"Recipient refused: {to_addr}")
    except Exception as e:
        raise SendError(f"SMTP error: {e}")

    if queue_id is not None:
        _mark_sent(queue_id)

    log.info("Sent to %s | subject: %s", to_addr, subject)
    return True


def _mark_sent(queue_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE email_queue SET status='sent', sent_at=datetime('now') WHERE id=?",
            (queue_id,)
        )


def _mark_failed(queue_id: int, error: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE email_queue SET status='failed', error=? WHERE id=?",
            (error, queue_id)
        )


def send_approved_batch(
    on_progress=None,
    on_error=None,
    dry_run: bool = False,
) -> dict:
    """
    Send all emails in the queue with status='approved'.
    Enforces daily limit and inter-send delay.

    on_progress(i, total, company): called after each successful send
    on_error(queue_id, company, error): called on failure (email skipped, not retried)
    dry_run=True: validates everything but doesn't actually send

    Returns: {sent: int, failed: int, skipped_daily_limit: int}
    """
    _check_configured()

    sent_today = _sent_today()
    remaining_budget = EMAIL_DAILY_MAX - sent_today

    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, company, contact_email, subject, body FROM email_queue WHERE status='approved' ORDER BY id"
        ).fetchall()

    if not rows:
        return {"sent": 0, "failed": 0, "skipped_daily_limit": 0}

    results = {"sent": 0, "failed": 0, "skipped_daily_limit": 0}

    for i, row in enumerate(rows):
        if results["sent"] >= remaining_budget:
            results["skipped_daily_limit"] += len(rows) - i
            break

        queue_id  = row["id"]
        company   = row["company"]
        to_addr   = row["contact_email"]
        subject   = row["subject"]
        body      = row["body"]

        try:
            if not dry_run:
                send_one(to_addr, subject, body, queue_id=queue_id)

            results["sent"] += 1
            if on_progress:
                on_progress(results["sent"], min(len(rows), remaining_budget), company)

            # Wait between sends — skip delay after last email
            if i < len(rows) - 1 and not dry_run:
                time.sleep(EMAIL_SEND_DELAY_SECONDS)

        except SendError as e:
            _mark_failed(queue_id, str(e))
            results["failed"] += 1
            if on_error:
                on_error(queue_id, company, str(e))

    return results


def check_gmail_connection() -> tuple[bool, str]:
    """Test Gmail credentials without sending. Returns (ok, message)."""
    try:
        _check_configured()
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        return True, "Gmail connected successfully"
    except SendError as e:
        return False, str(e)
    except smtplib.SMTPAuthenticationError:
        return False, "Authentication failed — check your App Password"
    except Exception as e:
        return False, f"Connection error: {e}"
