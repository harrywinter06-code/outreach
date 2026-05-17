# Autonomous Account Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give clawbot the ability to autonomously sign up for email-gated services, persist credentials safely, log back in across cycles, and spend money on those services via Stripe-Issuing virtual cards — without operator intervention for any non-ID-gated flow.

**Architecture:** Extends the existing `SkillCtx` extension seam (per memory `skillctx_is_extension_seam.md`) with one new `AccountsClient` and an extended `PaymentsClient`. Backend modules — encrypted SQLite vault, IMAP poller, Playwright `storage_state` store — sit under `src/clawbot/` as plumbing consumed only by the live SkillCtx classes. Builtin skills under `agents/skills/_builtin/{accounts,payments}/` expose the capability to organism-authored skills.

**Tech Stack:** Python 3.12+, stdlib (`sqlite3`, `imaplib`, `email`, `secrets`), `cryptography.fernet` (new direct dep — already a transitive dep of Stripe SDK), `stripe>=11` (already installed), `browser-use` (already installed), `httpx` (already installed). No new runtime infrastructure; one new pip dep that pulls in on next `docker compose build`.

**Out of scope (explicit):**
- Phone-gated signups (X, modern LinkedIn, Reddit-with-VPS-IP, Discord)
- ID/KYC-required services (banks, brokerages, anything regulated)
- Solving IP-reputation gates — caller accepts that some services will block VPS IPs

**Pre-mortem:** The most likely failure mode is a service flagging the browser as automated mid-signup, leaving a half-created account. Task 9 includes an explicit "abandon and mark zombie" path so the vault never holds an account whose recovery state is unknown.

---

## File Structure

**Create:**
- `src/clawbot/accounts_store.py` — encrypted SQLite credentials vault (Fernet-symmetric, key from env)
- `src/clawbot/email_reader.py` — IMAP poller; finds verification mails by alias, extracts link/code
- `src/clawbot/profile_store.py` — Playwright `storage_state.json` save/load per service
- `agents/skills/_builtin/accounts/create.py` — orchestrates signup → verify → vault
- `agents/skills/_builtin/accounts/login.py` — re-login using saved profile
- `agents/skills/_builtin/accounts/list.py` — list non-zombie accounts
- `agents/skills/_builtin/accounts/get.py` — fetch one account's creds
- `agents/skills/_builtin/payments/stripe_issue_card.py` — create a per-agent virtual card
- `agents/skills/_builtin/payments/stripe_freeze_card.py` — kill a card
- `agents/skills/_builtin/payments/stripe_list_authorizations.py` — list recent card activity
- `tests/test_accounts_store.py`
- `tests/test_email_reader.py`
- `tests/test_profile_store.py`
- `tests/test_stripe_issuing.py`
- `tests/test_accounts_ctx.py`
- `tests/test_builtin_accounts.py`
- `tests/test_builtin_payments_issuing.py`

**Modify:**
- `src/clawbot/skill_ctx.py` — extend `PaymentsClient` protocol with issuing methods; add `AccountsClient` protocol, `_NoopAccounts`, `_LiveAccounts`; extend `_NoopPayments`, `_LivePayments`; add `accounts` field to `SkillCtx`; update `make_noop_ctx`, `make_live_ctx`
- `src/clawbot/shadow_ctx.py` — import and wire `_NoopAccounts`
- `src/clawbot/config.py` — add `accounts_vault_key`, `accounts_db_path`, `imap_host`, `imap_port`, `imap_user`, `imap_password`, `email_domain`, `stripe_issuing_cardholder_id`
- `src/clawbot/directive_router.py` — pass new keys from settings into `make_live_ctx`
- `src/clawbot/browser_worker.py` — accept `profile_name` kwarg; integrate `profile_store`
- `pyproject.toml` — add `cryptography>=42` to dependencies
- `tests/test_builtin_skills.py` — extend `EXPECTED_BUILTINS` set with the new skill names

---

## Task 1: Add cryptography dependency + Accounts Vault (encrypted SQLite)

**Files:**
- Modify: `pyproject.toml` (dependencies array)
- Create: `src/clawbot/accounts_store.py`
- Create: `tests/test_accounts_store.py`

The vault is the foundation. Schema is intentionally small: one row per (service, email) pair. Passwords and cookies are Fernet-encrypted at write, decrypted on read; the encryption key lives only in env. `status` tracks `live` / `zombie` (signup got stuck) / `revoked`.

- [ ] **Step 1: Add cryptography to pyproject.toml**

Edit `pyproject.toml`, locate the `dependencies = [` block, add `"cryptography>=42",` after the last entry:

```toml
dependencies = [
    "redis>=5.0",
    "httpx>=0.27",
    "pydantic-settings>=2.0",
    "python-dotenv>=1.0",
    "pgvector>=0.3",
    "asyncpg>=0.29",
    "browser-use>=0.1",
    "langchain-openai>=0.1",
    "tenacity>=8.0",
    "fastembed>=0.3",
    "numpy>=1.26",
    "fastapi>=0.111",
    "uvicorn[standard]>=0.29",
    "stripe>=11.0",
    "cryptography>=42",
]
```

- [ ] **Step 2: Install the new dep locally**

Run: `uv sync`
Expected: cryptography appears in uv.lock; no other dep changes.

- [ ] **Step 3: Write the failing tests**

Create `tests/test_accounts_store.py`:

```python
"""Encrypted credentials vault — store, retrieve, status transitions."""
import tempfile
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from clawbot.accounts_store import AccountsStore, AccountRecord


@pytest.fixture
def vault(tmp_path: Path) -> AccountsStore:
    key = Fernet.generate_key().decode()
    db_path = tmp_path / "accounts.db"
    store = AccountsStore(db_path=str(db_path), encryption_key=key)
    store.init_schema()
    return store


def test_store_and_get_roundtrip(vault: AccountsStore):
    vault.store(service="substack", email="a@b.com", password="hunter2",
                cookies_json='{"k":"v"}')
    rec = vault.get(service="substack", email="a@b.com")
    assert rec is not None
    assert rec.service == "substack"
    assert rec.password == "hunter2"
    assert rec.cookies_json == '{"k":"v"}'
    assert rec.status == "live"


def test_password_is_encrypted_on_disk(vault: AccountsStore, tmp_path: Path):
    vault.store(service="medium", email="x@y.com", password="plaintext_secret",
                cookies_json="")
    raw = (tmp_path / "accounts.db").read_bytes()
    assert b"plaintext_secret" not in raw


def test_list_filters_by_status(vault: AccountsStore):
    vault.store(service="a", email="a@x.com", password="p1", cookies_json="")
    vault.store(service="b", email="b@x.com", password="p2", cookies_json="")
    vault.mark_zombie(service="b", email="b@x.com", reason="signup stuck")
    live = vault.list_accounts(status="live")
    zombie = vault.list_accounts(status="zombie")
    assert {r.service for r in live} == {"a"}
    assert {r.service for r in zombie} == {"b"}


def test_get_returns_none_for_missing(vault: AccountsStore):
    assert vault.get(service="nope", email="nope@x.com") is None


def test_store_is_idempotent_by_service_email(vault: AccountsStore):
    vault.store(service="s", email="e@x.com", password="p1", cookies_json="")
    vault.store(service="s", email="e@x.com", password="p2", cookies_json="newcookies")
    rec = vault.get(service="s", email="e@x.com")
    assert rec is not None
    assert rec.password == "p2"
    assert rec.cookies_json == "newcookies"


def test_record_account_dataclass_shape():
    rec = AccountRecord(
        service="s", email="e@x.com", password="p", cookies_json="{}",
        status="live", last_login_iso="2026-01-01T00:00:00+00:00",
        notes="",
    )
    assert rec.service == "s"
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `uv run pytest tests/test_accounts_store.py -v`
Expected: ImportError — module `clawbot.accounts_store` does not exist.

- [ ] **Step 5: Implement the vault**

Create `src/clawbot/accounts_store.py`:

```python
"""Encrypted SQLite credentials vault.

Schema: one row per (service, email) pair. Passwords and cookies are
Fernet-encrypted at write; the key lives only in env (`ACCOUNTS_VAULT_KEY`).
Status transitions: `live` → `zombie` (signup stuck) → `revoked`.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from cryptography.fernet import Fernet


@dataclass(frozen=True)
class AccountRecord:
    service: str
    email: str
    password: str
    cookies_json: str
    status: str
    last_login_iso: str
    notes: str


class AccountsStore:
    def __init__(self, db_path: str, encryption_key: str) -> None:
        self._db_path = db_path
        self._fernet = Fernet(encryption_key.encode() if isinstance(encryption_key, str) else encryption_key)

    def init_schema(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS accounts (
                    service TEXT NOT NULL,
                    email TEXT NOT NULL,
                    password_enc BLOB NOT NULL,
                    cookies_enc BLOB NOT NULL,
                    status TEXT NOT NULL DEFAULT 'live',
                    last_login_iso TEXT NOT NULL,
                    notes TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (service, email)
                )
            """)

    def _enc(self, text: str) -> bytes:
        return self._fernet.encrypt(text.encode("utf-8"))

    def _dec(self, blob: bytes) -> str:
        return self._fernet.decrypt(blob).decode("utf-8")

    def store(self, *, service: str, email: str, password: str, cookies_json: str,
              notes: str = "") -> None:
        now = datetime.now(UTC).isoformat()
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO accounts (service, email, password_enc, cookies_enc,
                                      status, last_login_iso, notes)
                VALUES (?, ?, ?, ?, 'live', ?, ?)
                ON CONFLICT(service, email) DO UPDATE SET
                    password_enc=excluded.password_enc,
                    cookies_enc=excluded.cookies_enc,
                    last_login_iso=excluded.last_login_iso,
                    notes=excluded.notes
                """,
                (service, email, self._enc(password), self._enc(cookies_json), now, notes),
            )

    def get(self, *, service: str, email: str) -> AccountRecord | None:
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT service, email, password_enc, cookies_enc, status, last_login_iso, notes "
                "FROM accounts WHERE service=? AND email=?",
                (service, email),
            ).fetchone()
        if row is None:
            return None
        return AccountRecord(
            service=row[0], email=row[1],
            password=self._dec(row[2]), cookies_json=self._dec(row[3]),
            status=row[4], last_login_iso=row[5], notes=row[6],
        )

    def list_accounts(self, *, status: str | None = None) -> list[AccountRecord]:
        with sqlite3.connect(self._db_path) as conn:
            if status is None:
                rows = conn.execute(
                    "SELECT service, email, password_enc, cookies_enc, status, last_login_iso, notes "
                    "FROM accounts ORDER BY service"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT service, email, password_enc, cookies_enc, status, last_login_iso, notes "
                    "FROM accounts WHERE status=? ORDER BY service",
                    (status,),
                ).fetchall()
        return [
            AccountRecord(
                service=r[0], email=r[1],
                password=self._dec(r[2]), cookies_json=self._dec(r[3]),
                status=r[4], last_login_iso=r[5], notes=r[6],
            )
            for r in rows
        ]

    def mark_zombie(self, *, service: str, email: str, reason: str) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "UPDATE accounts SET status='zombie', notes=? WHERE service=? AND email=?",
                (reason, service, email),
            )

    def update_cookies(self, *, service: str, email: str, cookies_json: str) -> None:
        now = datetime.now(UTC).isoformat()
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "UPDATE accounts SET cookies_enc=?, last_login_iso=? WHERE service=? AND email=?",
                (self._enc(cookies_json), now, service, email),
            )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_accounts_store.py -v`
Expected: 6 passed.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock src/clawbot/accounts_store.py tests/test_accounts_store.py
git commit -m "feat: encrypted SQLite accounts vault (Fernet)"
```

---

## Task 2: Email reader (IMAP poller for verification mails)

**Files:**
- Create: `src/clawbot/email_reader.py`
- Create: `tests/test_email_reader.py`

`EmailReader.find_verification(alias, since_minutes=10)` polls the inbox for the most recent mail addressed to `alias@email_domain` and returns:
- A confirmation URL if the body contains a link with confirmation/verify/activate in the path, OR
- A 6-digit numeric code if the body has one matching `\b\d{6}\b`, OR
- `None` if no mail arrived in the window.

`imaplib` blocks; we wrap it in `asyncio.to_thread` to stay event-loop-safe (matches the existing `_LivePayments` pattern in skill_ctx.py).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_email_reader.py`:

```python
"""IMAP-based verification mail extraction."""
import asyncio
from unittest.mock import MagicMock, patch

import pytest

from clawbot.email_reader import EmailReader, VerificationResult


def _fake_message(to: str, body: str) -> bytes:
    return (
        f"To: {to}\r\n"
        f"From: noreply@service.com\r\n"
        f"Subject: Verify\r\n"
        f"\r\n"
        f"{body}\r\n"
    ).encode("utf-8")


def test_finds_six_digit_code():
    msg = _fake_message("substack+sub123@example.com", "Your code is 482917, valid 10 min.")
    fake_imap = MagicMock()
    fake_imap.search.return_value = ("OK", [b"1"])
    fake_imap.fetch.return_value = ("OK", [(b"1 (RFC822 {123}", msg)])

    reader = EmailReader(host="imap.x", port=993, user="u", password="p", domain="example.com")
    with patch("clawbot.email_reader.imaplib.IMAP4_SSL", return_value=fake_imap):
        result = asyncio.run(reader.find_verification(alias="substack+sub123", since_minutes=10))

    assert isinstance(result, VerificationResult)
    assert result.code == "482917"
    assert result.url is None


def test_finds_confirmation_url():
    body = "Click https://service.com/verify?token=abc123 to confirm."
    msg = _fake_message("medium+m1@example.com", body)
    fake_imap = MagicMock()
    fake_imap.search.return_value = ("OK", [b"7"])
    fake_imap.fetch.return_value = ("OK", [(b"7 (RFC822 {123}", msg)])

    reader = EmailReader(host="x", port=993, user="u", password="p", domain="example.com")
    with patch("clawbot.email_reader.imaplib.IMAP4_SSL", return_value=fake_imap):
        result = asyncio.run(reader.find_verification(alias="medium+m1", since_minutes=10))

    assert result.url == "https://service.com/verify?token=abc123"
    assert result.code is None


def test_returns_none_when_no_match():
    fake_imap = MagicMock()
    fake_imap.search.return_value = ("OK", [b""])  # no message ids
    reader = EmailReader(host="x", port=993, user="u", password="p", domain="example.com")
    with patch("clawbot.email_reader.imaplib.IMAP4_SSL", return_value=fake_imap):
        result = asyncio.run(reader.find_verification(alias="x+y", since_minutes=10))
    assert result is None


def test_alias_isolation_only_matches_alias():
    """A message to a different alias must NOT match — alias is required in TO."""
    msg = _fake_message("OTHER+xyz@example.com", "Code 111111")
    fake_imap = MagicMock()
    fake_imap.search.return_value = ("OK", [b"1"])
    fake_imap.fetch.return_value = ("OK", [(b"1 (RFC822 {123}", msg)])

    reader = EmailReader(host="x", port=993, user="u", password="p", domain="example.com")
    with patch("clawbot.email_reader.imaplib.IMAP4_SSL", return_value=fake_imap):
        result = asyncio.run(reader.find_verification(alias="substack+sub1", since_minutes=10))
    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_email_reader.py -v`
Expected: ImportError — `clawbot.email_reader` not found.

- [ ] **Step 3: Implement the email reader**

Create `src/clawbot/email_reader.py`:

```python
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

    def _sync_find(self, alias: str, since_minutes: int) -> VerificationResult | None:
        target_address = f"{alias}@{self._domain}".lower()
        since = datetime.now(UTC) - timedelta(minutes=since_minutes)
        since_str = since.strftime("%d-%b-%Y")
        try:
            imap = imaplib.IMAP4_SSL(self._host, self._port)
            imap.login(self._user, self._password)
            imap.select("INBOX")
            status, data = imap.search(None, f'(SINCE "{since_str}")')
            if status != "OK" or not data or not data[0]:
                return None
            msg_ids = data[0].split()
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
            try:
                imap.close()  # type: ignore[union-attr]
                imap.logout()  # type: ignore[union-attr]
            except Exception:
                pass

    @staticmethod
    def _extract_body(msg: email.message.Message) -> str:
        if msg.is_multipart():
            parts = []
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    payload = part.get_payload(decode=True)
                    if isinstance(payload, bytes):
                        parts.append(payload.decode("utf-8", errors="replace"))
            return "\n".join(parts)
        payload = msg.get_payload(decode=True)
        if isinstance(payload, bytes):
            return payload.decode("utf-8", errors="replace")
        return str(payload or "")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_email_reader.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/clawbot/email_reader.py tests/test_email_reader.py
git commit -m "feat: IMAP email reader extracts verification URL/code per alias"
```

---

## Task 3: Profile store (Playwright storage_state persistence)

**Files:**
- Create: `src/clawbot/profile_store.py`
- Create: `tests/test_profile_store.py`

Stores Playwright `storage_state` JSON blobs per service under `data/profiles/<service>.json`. The point: avoid re-logging-in on every cycle, which is how services flag accounts as bot traffic.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_profile_store.py`:

```python
"""Per-service Playwright storage_state persistence."""
import json
from pathlib import Path

import pytest

from clawbot.profile_store import ProfileStore


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    return ProfileStore(root=str(tmp_path / "profiles"))


def test_save_and_load_roundtrip(store: ProfileStore):
    state = {"cookies": [{"name": "session", "value": "abc"}], "origins": []}
    store.save("substack", state)
    loaded = store.load("substack")
    assert loaded == state


def test_load_missing_returns_none(store: ProfileStore):
    assert store.load("never_saved") is None


def test_exists_reflects_saved_state(store: ProfileStore):
    assert store.exists("medium") is False
    store.save("medium", {"cookies": []})
    assert store.exists("medium") is True


def test_save_overwrites_existing(store: ProfileStore):
    store.save("s", {"cookies": [{"name": "old"}]})
    store.save("s", {"cookies": [{"name": "new"}]})
    loaded = store.load("s")
    assert loaded == {"cookies": [{"name": "new"}]}


def test_service_name_path_traversal_rejected(store: ProfileStore):
    """A service name with .. or / must not escape the root."""
    with pytest.raises(ValueError):
        store.save("../etc/passwd", {"cookies": []})
    with pytest.raises(ValueError):
        store.save("foo/bar", {"cookies": []})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_profile_store.py -v`
Expected: ImportError — `clawbot.profile_store` not found.

- [ ] **Step 3: Implement the profile store**

Create `src/clawbot/profile_store.py`:

```python
"""Per-service Playwright storage_state persistence.

Stored at `<root>/<service>.json`. Service names must be slug-safe —
a name containing `/`, `..`, or other path components is rejected at
write time, defeating path-traversal payloads from organism-authored skills."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_SERVICE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class ProfileStore:
    def __init__(self, root: str) -> None:
        self._root = Path(root)

    def _path(self, service: str) -> Path:
        if not _SERVICE_NAME_RE.match(service):
            raise ValueError(f"unsafe service name: {service!r}")
        return self._root / f"{service}.json"

    def save(self, service: str, state: dict[str, Any]) -> None:
        path = self._path(service)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state), encoding="utf-8")

    def load(self, service: str) -> dict[str, Any] | None:
        path = self._path(service)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def exists(self, service: str) -> bool:
        return self._path(service).exists()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_profile_store.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/clawbot/profile_store.py tests/test_profile_store.py
git commit -m "feat: ProfileStore persists Playwright storage_state per service"
```

---

## Task 4: Extend PaymentsClient with Stripe Issuing methods

**Files:**
- Modify: `src/clawbot/skill_ctx.py` (PaymentsClient protocol, _NoopPayments, _LivePayments)
- Create: `tests/test_stripe_issuing.py`

Adds three methods to the existing `PaymentsClient` protocol: `issue_card`, `freeze_card`, `list_authorizations`. Real implementation uses `stripe.issuing.Card.create/update` and `stripe.issuing.Authorization.list` through `asyncio.to_thread` (matches the existing pattern in `_LivePayments`).

Cardholder model: one company-type cardholder per clawbot deployment, ID stored in `STRIPE_ISSUING_CARDHOLDER_ID`. Each card cites this cardholder. The operator creates the cardholder once via the Stripe dashboard or a one-off script.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_stripe_issuing.py`:

```python
"""Stripe Issuing — virtual card create, freeze, list authorizations."""
import asyncio
from unittest.mock import MagicMock, patch


def test_noop_issue_card_returns_stub():
    from clawbot.skill_ctx import make_noop_ctx
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    card = asyncio.run(ctx.payments.issue_card(
        cardholder_id="ich_test", daily_limit_usd=10, agent_id="ceo",
    ))
    assert card["id"].startswith("ic_noop")
    assert card["last4"]


def test_noop_freeze_card_returns_stub():
    from clawbot.skill_ctx import make_noop_ctx
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    result = asyncio.run(ctx.payments.freeze_card(card_id="ic_x"))
    assert result["id"] == "ic_x"
    assert result["status"] == "canceled"


def test_noop_list_authorizations_returns_empty():
    from clawbot.skill_ctx import make_noop_ctx
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    auths = asyncio.run(ctx.payments.list_authorizations(card_id="ic_x", limit=5))
    assert auths == []


def test_live_issue_card_calls_stripe_with_spending_controls():
    from clawbot.skill_ctx import _LivePayments

    fake_card = MagicMock()
    fake_card.to_dict.return_value = {
        "id": "ic_real_abc", "last4": "4242", "exp_month": 12, "exp_year": 2028,
        "status": "active", "cardholder": "ich_x",
    }

    payments = _LivePayments(secret_key="sk_test_123")
    with patch("clawbot.skill_ctx.stripe") as stripe_mod:
        stripe_mod.issuing.Card.create.return_value = fake_card
        result = asyncio.run(payments.issue_card(
            cardholder_id="ich_x", daily_limit_usd=25, agent_id="cmo",
        ))

    stripe_mod.issuing.Card.create.assert_called_once()
    kwargs = stripe_mod.issuing.Card.create.call_args.kwargs
    assert kwargs["cardholder"] == "ich_x"
    assert kwargs["type"] == "virtual"
    assert kwargs["currency"] == "usd"
    # daily limit enforced via spending_controls
    sc = kwargs["spending_controls"]
    assert any(
        sl["interval"] == "daily" and sl["amount"] == 2500
        for sl in sc["spending_limits"]
    )
    # Metadata records which agent owns the card
    assert kwargs["metadata"]["agent_id"] == "cmo"
    assert result["id"] == "ic_real_abc"


def test_live_freeze_card_cancels_via_update():
    from clawbot.skill_ctx import _LivePayments

    fake_card = MagicMock()
    fake_card.to_dict.return_value = {"id": "ic_x", "status": "canceled"}

    payments = _LivePayments(secret_key="sk_test_123")
    with patch("clawbot.skill_ctx.stripe") as stripe_mod:
        stripe_mod.issuing.Card.modify.return_value = fake_card
        result = asyncio.run(payments.freeze_card(card_id="ic_x"))

    stripe_mod.issuing.Card.modify.assert_called_once_with("ic_x", status="canceled")
    assert result["status"] == "canceled"


def test_live_list_authorizations_paginates():
    from clawbot.skill_ctx import _LivePayments

    a1 = MagicMock(); a1.to_dict.return_value = {"id": "iauth_1", "amount": 500}
    a2 = MagicMock(); a2.to_dict.return_value = {"id": "iauth_2", "amount": 700}
    fake_list = MagicMock()
    fake_list.auto_paging_iter.return_value = iter([a1, a2])

    payments = _LivePayments(secret_key="sk_test_123")
    with patch("clawbot.skill_ctx.stripe") as stripe_mod:
        stripe_mod.issuing.Authorization.list.return_value = fake_list
        result = asyncio.run(payments.list_authorizations(card_id="ic_x", limit=10))

    stripe_mod.issuing.Authorization.list.assert_called_once()
    assert len(result) == 2
    assert result[0]["id"] == "iauth_1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_stripe_issuing.py -v`
Expected: AttributeError — `issue_card` not on payments.

- [ ] **Step 3: Extend the PaymentsClient protocol**

In `src/clawbot/skill_ctx.py`, locate the `PaymentsClient` Protocol class and add three method signatures after the existing `refund`:

```python
class PaymentsClient(Protocol):
    async def create_product(self, *, name: str, description: str) -> dict[str, Any]: ...
    async def create_price(self, *, product_id: str, amount_pence: int, currency: str = "gbp", recurring: bool = False) -> dict[str, Any]: ...
    async def create_payment_link(self, *, price_id: str, quantity: int = 1) -> dict[str, Any]: ...
    async def list_charges(self, *, limit: int = 20) -> list[dict[str, Any]]: ...
    async def refund(self, *, charge_id: str, amount_pence: int | None = None) -> dict[str, Any]: ...
    async def issue_card(self, *, cardholder_id: str, daily_limit_usd: int, agent_id: str) -> dict[str, Any]: ...
    async def freeze_card(self, *, card_id: str) -> dict[str, Any]: ...
    async def list_authorizations(self, *, card_id: str, limit: int = 20) -> list[dict[str, Any]]: ...
```

- [ ] **Step 4: Extend _NoopPayments**

In `src/clawbot/skill_ctx.py`, locate `class _NoopPayments` and append the three stub methods at the end of the class:

```python
    async def issue_card(self, **kwargs: Any) -> dict[str, Any]:
        return {
            "id": "ic_noop_abc", "last4": "4242",
            "exp_month": 12, "exp_year": 2030, "status": "active",
            "cardholder": kwargs.get("cardholder_id", ""),
        }

    async def freeze_card(self, *, card_id: str) -> dict[str, Any]:
        return {"id": card_id, "status": "canceled"}

    async def list_authorizations(self, *, card_id: str, limit: int = 20) -> list[dict[str, Any]]:
        return []
```

- [ ] **Step 5: Extend _LivePayments**

In `src/clawbot/skill_ctx.py`, locate `class _LivePayments` and append the three live methods at the end of the class:

```python
    async def issue_card(
        self, *, cardholder_id: str, daily_limit_usd: int, agent_id: str,
    ) -> dict[str, Any]:
        amount_cents = daily_limit_usd * 100
        card = await asyncio.to_thread(
            stripe.issuing.Card.create,  # type: ignore[union-attr]
            cardholder=cardholder_id,
            currency="usd",
            type="virtual",
            spending_controls={
                "spending_limits": [
                    {"amount": amount_cents, "interval": "daily"},
                ],
            },
            metadata={"agent_id": agent_id},
        )
        return card.to_dict()

    async def freeze_card(self, *, card_id: str) -> dict[str, Any]:
        card = await asyncio.to_thread(
            stripe.issuing.Card.modify, card_id, status="canceled",  # type: ignore[union-attr]
        )
        return card.to_dict()

    async def list_authorizations(self, *, card_id: str, limit: int = 20) -> list[dict[str, Any]]:
        auths = await asyncio.to_thread(
            stripe.issuing.Authorization.list, card=card_id, limit=limit,  # type: ignore[union-attr]
        )
        return [a.to_dict() for a in auths.auto_paging_iter()][:limit]
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_stripe_issuing.py -v`
Expected: 6 passed.

- [ ] **Step 7: Commit**

```bash
git add src/clawbot/skill_ctx.py tests/test_stripe_issuing.py
git commit -m "feat: PaymentsClient gains Stripe Issuing methods (issue/freeze/list-auth)"
```

---

## Task 5: Config additions for vault + IMAP + email + issuing

**Files:**
- Modify: `src/clawbot/config.py`

All operator-managed env vars in one commit so subsequent tasks can wire them up.

- [ ] **Step 1: Append new fields to Settings**

In `src/clawbot/config.py`, locate the block ending with `stripe_secret_key: str = ""` (and the Tavily/Firecrawl lines below it if they're there). Add the new fields just after Tavily/Firecrawl, before the `active_provider_names` property:

```python
    # Account-management infrastructure — all optional.
    # Without these, _LiveAccounts falls back to _NoopAccounts so existing
    # behaviour is unchanged. Operator setup:
    #   1. Buy a domain (~$10/yr) and enable Cloudflare Email Routing free tier
    #   2. Generate vault key: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    #   3. Create a company-type Issuing cardholder once in Stripe dashboard;
    #      copy the ich_... id into STRIPE_ISSUING_CARDHOLDER_ID
    accounts_vault_key: str = ""
    accounts_db_path: str = "data/accounts.db"
    imap_host: str = ""
    imap_port: int = 993
    imap_user: str = ""
    imap_password: str = ""
    email_domain: str = ""
    stripe_issuing_cardholder_id: str = ""
```

- [ ] **Step 2: Run pytest to confirm no regression**

Run: `uv run pytest tests/test_search_ctx.py tests/test_accounts_store.py tests/test_email_reader.py tests/test_profile_store.py tests/test_stripe_issuing.py -v`
Expected: all green (no test depends on these fields existing yet, but Settings must still import).

- [ ] **Step 3: Commit**

```bash
git add src/clawbot/config.py
git commit -m "feat: config keys for accounts vault, IMAP, email domain, Stripe Issuing"
```

---

## Task 6: AccountsClient — protocol, noop, SkillCtx field

**Files:**
- Modify: `src/clawbot/skill_ctx.py` (Protocol, _NoopAccounts, SkillCtx field, make_noop_ctx)
- Modify: `src/clawbot/shadow_ctx.py` (import _NoopAccounts, wire in make_shadow_ctx)
- Create: `tests/test_accounts_ctx.py`

Defines the public contract for skills. `_LiveAccounts` comes in the next task; this task just lays in the protocol + noop so the SkillCtx shape is correct.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_accounts_ctx.py`:

```python
"""AccountsClient protocol — noop behavior, SkillCtx wiring."""
import asyncio


def test_noop_accounts_create_returns_stub():
    from clawbot.skill_ctx import make_noop_ctx
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    result = asyncio.run(ctx.accounts.create_account(
        service="substack", signup_url="https://substack.com/signup",
    ))
    assert result["status"] == "noop"
    assert result["service"] == "substack"


def test_noop_accounts_get_returns_none():
    from clawbot.skill_ctx import make_noop_ctx
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    result = asyncio.run(ctx.accounts.get_account(service="substack", email="x@y.com"))
    assert result is None


def test_noop_accounts_list_returns_empty():
    from clawbot.skill_ctx import make_noop_ctx
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    assert asyncio.run(ctx.accounts.list_accounts(status="live")) == []


def test_skill_ctx_has_accounts_field():
    from clawbot.skill_ctx import make_noop_ctx, SkillCtx
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    assert hasattr(ctx, "accounts")
    # frozen dataclass — field must be in __dataclass_fields__
    assert "accounts" in SkillCtx.__dataclass_fields__


def test_shadow_ctx_has_accounts_field():
    from clawbot.shadow_ctx import make_shadow_ctx
    ctx = make_shadow_ctx(caller_id="t", budget_usd=0)
    assert hasattr(ctx, "accounts")
    assert asyncio.run(ctx.accounts.list_accounts(status="live")) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_accounts_ctx.py -v`
Expected: AttributeError — `accounts` not on ctx.

- [ ] **Step 3: Add the AccountsClient protocol**

In `src/clawbot/skill_ctx.py`, after the `SearchClient` Protocol class, add:

```python
class AccountsClient(Protocol):
    async def create_account(
        self, *, service: str, signup_url: str, notes: str = "",
    ) -> dict[str, Any]: ...
    async def get_account(self, *, service: str, email: str) -> dict[str, Any] | None: ...
    async def list_accounts(self, *, status: str | None = None) -> list[dict[str, Any]]: ...
    async def mark_zombie(self, *, service: str, email: str, reason: str) -> dict[str, Any]: ...
```

- [ ] **Step 4: Add the `accounts` field to the SkillCtx dataclass**

In `src/clawbot/skill_ctx.py`, in the `@dataclass(frozen=True) class SkillCtx:` block, add `accounts: AccountsClient` after `search: SearchClient`:

```python
@dataclass(frozen=True)
class SkillCtx:
    http: HttpClient
    sql: SqlClient
    llm: LlmClient
    vector: VectorClient
    secret: SecretClient
    fs: FsClient
    time: TimeClient
    operator: OperatorClient
    bus: BusClient
    log: LogClient
    browser: BrowserClient
    payments: PaymentsClient
    social: SocialClient
    email: EmailClient
    search: SearchClient
    accounts: AccountsClient
    caller_id: str
    budget_usd: float
```

- [ ] **Step 5: Add _NoopAccounts**

In `src/clawbot/skill_ctx.py`, after `class _NoopSearch:`, add:

```python
class _NoopAccounts:
    async def create_account(
        self, *, service: str, signup_url: str, notes: str = "",
    ) -> dict[str, Any]:
        return {"status": "noop", "service": service, "email": "", "url": signup_url}

    async def get_account(self, *, service: str, email: str) -> dict[str, Any] | None:
        return None

    async def list_accounts(self, *, status: str | None = None) -> list[dict[str, Any]]:
        return []

    async def mark_zombie(self, *, service: str, email: str, reason: str) -> dict[str, Any]:
        return {"service": service, "email": email, "status": "zombie", "reason": reason}
```

- [ ] **Step 6: Wire _NoopAccounts into make_noop_ctx**

In `src/clawbot/skill_ctx.py`, find `make_noop_ctx` and add `accounts=_NoopAccounts()` to the SkillCtx construction:

```python
def make_noop_ctx(*, caller_id: str, budget_usd: float) -> SkillCtx:
    return SkillCtx(
        http=_NoopHttp(), sql=_NoopSql(), llm=_NoopLlm(), vector=_NoopVector(),
        secret=_NoopSecret(), fs=_NoopFs(), time=_NoopTime(), operator=_NoopOperator(),
        bus=_NoopBus(), log=_NoopLog(), browser=_NoopBrowser(), payments=_NoopPayments(),
        social=_NoopSocial(), email=_NoopEmail(), search=_NoopSearch(),
        accounts=_NoopAccounts(),
        caller_id=caller_id, budget_usd=budget_usd,
    )
```

- [ ] **Step 7: Wire _NoopAccounts into shadow_ctx**

In `src/clawbot/shadow_ctx.py`, add `_NoopAccounts` to the imports from `clawbot.skill_ctx` (keep alphabetical order), and add `accounts=_NoopAccounts()` to the `make_shadow_ctx` SkillCtx construction:

```python
from clawbot.skill_ctx import (
    SkillCtx,
    _NoopAccounts,
    _NoopBrowser,
    _NoopBus,
    _NoopEmail,
    _NoopLlm,
    _NoopLog,
    _NoopOperator,
    _NoopPayments,
    _NoopSearch,
    _NoopSecret,
    _NoopSocial,
    _NoopSql,
    _NoopTime,
    _NoopVector,
)
```

And in `make_shadow_ctx`:

```python
    return SkillCtx(
        http=_ShadowHttp(),
        sql=_NoopSql(),
        llm=_NoopLlm(),
        vector=_NoopVector(),
        secret=_NoopSecret(),
        fs=_ShadowFs(),
        time=_NoopTime(),
        operator=_NoopOperator(),
        bus=_NoopBus(),
        log=_NoopLog(),
        browser=_NoopBrowser(),
        payments=_NoopPayments(),
        social=_NoopSocial(),
        email=_NoopEmail(),
        search=_NoopSearch(),
        accounts=_NoopAccounts(),
        caller_id=caller_id,
        budget_usd=budget_usd,
    )
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `uv run pytest tests/test_accounts_ctx.py tests/test_search_ctx.py -v`
Expected: 13 passed (5 new + 8 existing).

- [ ] **Step 9: Commit**

```bash
git add src/clawbot/skill_ctx.py src/clawbot/shadow_ctx.py tests/test_accounts_ctx.py
git commit -m "feat: AccountsClient protocol + noop wired into SkillCtx"
```

---

## Task 7: _LiveAccounts orchestrator + make_live_ctx wiring

**Files:**
- Modify: `src/clawbot/skill_ctx.py` (add _LiveAccounts, update make_live_ctx signature + body)
- Modify: `src/clawbot/directive_router.py` (pass new keys from settings)
- Modify: `tests/test_accounts_ctx.py` (live orchestration tests with mocks)

`_LiveAccounts.create_account` is the central orchestrator. It:
1. Generates `alias = f"{service}-{timestamp}"` and `email = f"{alias}@{email_domain}"`
2. Generates a 32-character hex password via `secrets.token_hex(16)`
3. Records a pre-state row in the vault (status `pending`) so a mid-flow crash leaves a traceable artifact
4. Calls `_LiveBrowser.run` with a task that fills the signup form and waits for verification
5. Polls `EmailReader.find_verification` for up to 120s
6. If verification found: completes signup via browser; saves storage_state; transitions vault row to `live`
7. If verification not found OR browser failed: marks the row `zombie` with the failure reason

For initial wiring, the browser orchestration is a single `ctx.browser.run` call that the agent can later override with a richer flow. The signup task string is what makes browser-use do the right thing — it's deliberately a single coarse step rather than ten micro-steps, matching how browser-use is designed to be driven.

- [ ] **Step 1: Append the live orchestration tests**

Append to `tests/test_accounts_ctx.py`:

```python
def test_live_accounts_creates_signup_and_stores_creds(tmp_path):
    """Happy path: signup task succeeds, email arrives, creds vault'd."""
    from unittest.mock import AsyncMock, patch
    from cryptography.fernet import Fernet
    from clawbot.skill_ctx import _LiveAccounts
    from clawbot.accounts_store import AccountsStore
    from clawbot.profile_store import ProfileStore
    from clawbot.email_reader import VerificationResult

    vault = AccountsStore(db_path=str(tmp_path / "v.db"),
                          encryption_key=Fernet.generate_key().decode())
    vault.init_schema()
    profiles = ProfileStore(root=str(tmp_path / "p"))

    fake_browser = AsyncMock()
    fake_browser.run = AsyncMock(return_value={
        "success": True, "output": '{"storage_state": {"cookies": [{"name":"s"}]}}',
        "error": "", "task": "...",
    })
    fake_email = AsyncMock()
    fake_email.find_verification = AsyncMock(return_value=VerificationResult(
        url="https://service.com/verify?t=abc", code=None,
    ))

    live = _LiveAccounts(
        vault=vault, profiles=profiles,
        browser=fake_browser, email_reader=fake_email,
        email_domain="example.com",
    )
    result = asyncio.run(live.create_account(
        service="substack", signup_url="https://substack.com/signup",
    ))

    assert result["status"] == "live"
    assert result["service"] == "substack"
    assert "@example.com" in result["email"]
    # vault has the row
    rows = vault.list_accounts(status="live")
    assert any(r.service == "substack" for r in rows)


def test_live_accounts_marks_zombie_on_browser_failure(tmp_path):
    from unittest.mock import AsyncMock
    from cryptography.fernet import Fernet
    from clawbot.skill_ctx import _LiveAccounts
    from clawbot.accounts_store import AccountsStore
    from clawbot.profile_store import ProfileStore

    vault = AccountsStore(db_path=str(tmp_path / "v.db"),
                          encryption_key=Fernet.generate_key().decode())
    vault.init_schema()
    profiles = ProfileStore(root=str(tmp_path / "p"))

    fake_browser = AsyncMock()
    fake_browser.run = AsyncMock(return_value={
        "success": False, "output": "", "error": "captcha challenge",
        "task": "...",
    })
    fake_email = AsyncMock()

    live = _LiveAccounts(
        vault=vault, profiles=profiles,
        browser=fake_browser, email_reader=fake_email,
        email_domain="example.com",
    )
    result = asyncio.run(live.create_account(
        service="x", signup_url="https://x.com/signup",
    ))

    assert result["status"] == "zombie"
    assert "captcha" in result["reason"]
    rows = vault.list_accounts(status="zombie")
    assert any(r.service == "x" for r in rows)


def test_live_accounts_marks_zombie_on_no_verification_mail(tmp_path):
    from unittest.mock import AsyncMock
    from cryptography.fernet import Fernet
    from clawbot.skill_ctx import _LiveAccounts
    from clawbot.accounts_store import AccountsStore
    from clawbot.profile_store import ProfileStore

    vault = AccountsStore(db_path=str(tmp_path / "v.db"),
                          encryption_key=Fernet.generate_key().decode())
    vault.init_schema()
    profiles = ProfileStore(root=str(tmp_path / "p"))

    fake_browser = AsyncMock()
    fake_browser.run = AsyncMock(return_value={
        "success": True, "output": "{}", "error": "", "task": "...",
    })
    fake_email = AsyncMock()
    fake_email.find_verification = AsyncMock(return_value=None)

    live = _LiveAccounts(
        vault=vault, profiles=profiles,
        browser=fake_browser, email_reader=fake_email,
        email_domain="example.com",
        verification_poll_timeout_s=0.1,
        verification_poll_interval_s=0.05,
    )
    result = asyncio.run(live.create_account(
        service="medium", signup_url="https://medium.com/signup",
    ))

    assert result["status"] == "zombie"
    assert "verification" in result["reason"].lower()


def test_live_accounts_list_and_get_decrypt(tmp_path):
    from cryptography.fernet import Fernet
    from clawbot.skill_ctx import _LiveAccounts
    from clawbot.accounts_store import AccountsStore
    from clawbot.profile_store import ProfileStore
    from unittest.mock import AsyncMock

    vault = AccountsStore(db_path=str(tmp_path / "v.db"),
                          encryption_key=Fernet.generate_key().decode())
    vault.init_schema()
    vault.store(service="s", email="e@x.com", password="pw", cookies_json="{}")
    profiles = ProfileStore(root=str(tmp_path / "p"))

    live = _LiveAccounts(
        vault=vault, profiles=profiles,
        browser=AsyncMock(), email_reader=AsyncMock(),
        email_domain="example.com",
    )
    accounts = asyncio.run(live.list_accounts(status="live"))
    assert len(accounts) == 1
    assert accounts[0]["password"] == "pw"

    one = asyncio.run(live.get_account(service="s", email="e@x.com"))
    assert one is not None
    assert one["password"] == "pw"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_accounts_ctx.py -v`
Expected: ImportError — `_LiveAccounts` not in skill_ctx.

- [ ] **Step 3: Implement _LiveAccounts**

In `src/clawbot/skill_ctx.py`, after `_LiveSearch`, add:

```python
class _LiveAccounts:
    """Orchestrates autonomous account signup → verify → vault storage.

    The signup task is a single browser-use directive rather than a scripted
    DOM walk: browser-use's strength is self-healing across DOM changes, so
    we hand it the goal and let it find the form fields. The verification
    poll runs after browser success and times out into a zombie state if no
    mail arrives — better than blocking forever on a service that silently
    rate-limited us."""

    def __init__(
        self,
        *,
        vault: Any,
        profiles: Any,
        browser: Any,
        email_reader: Any,
        email_domain: str,
        verification_poll_timeout_s: float = 120.0,
        verification_poll_interval_s: float = 5.0,
    ) -> None:
        self._vault = vault
        self._profiles = profiles
        self._browser = browser
        self._email_reader = email_reader
        self._email_domain = email_domain
        self._verify_timeout = verification_poll_timeout_s
        self._verify_interval = verification_poll_interval_s

    async def create_account(
        self, *, service: str, signup_url: str, notes: str = "",
    ) -> dict[str, Any]:
        import secrets as _secrets
        import json as _json

        timestamp = int(datetime.now(UTC).timestamp())
        alias = f"{service}-{timestamp}"
        email_addr = f"{alias}@{self._email_domain}"
        password = _secrets.token_hex(16)

        # Step 1: drive the signup form via browser-use.
        task = (
            f"Sign up for {service} at {signup_url}. "
            f"Use email '{email_addr}' and password '{password}'. "
            f"Complete any inline form fields needed. "
            f"After submitting, wait for the page that says a verification email was sent. "
            f"Then return the page's storage_state as JSON in your output."
        )
        browser_result = await self._browser.run(task=task, max_steps=30)
        if not browser_result.get("success"):
            err = browser_result.get("error", "unknown")
            self._vault.store(
                service=service, email=email_addr, password=password,
                cookies_json="", notes=f"signup failed: {err}",
            )
            self._vault.mark_zombie(
                service=service, email=email_addr,
                reason=f"browser failure: {err}",
            )
            return {"status": "zombie", "service": service, "email": email_addr,
                    "reason": f"browser failure: {err}"}

        # Step 2: poll for verification mail.
        verification = await self._poll_verification(alias)
        if verification is None:
            self._vault.store(
                service=service, email=email_addr, password=password,
                cookies_json="", notes="verification timeout",
            )
            self._vault.mark_zombie(
                service=service, email=email_addr,
                reason="verification mail not received in window",
            )
            return {"status": "zombie", "service": service, "email": email_addr,
                    "reason": "verification timeout"}

        # Step 3: drive browser to complete verification.
        if verification.url:
            await self._browser.run(
                task=f"Open URL {verification.url} to complete signup verification. "
                     f"Return resulting storage_state.",
                max_steps=10,
            )
        elif verification.code:
            await self._browser.run(
                task=f"On the current page, enter the verification code {verification.code}. "
                     f"Return resulting storage_state.",
                max_steps=10,
            )

        # Step 4: persist creds + profile.
        storage_state = self._extract_storage_state(browser_result.get("output", ""))
        cookies_json = _json.dumps(storage_state) if storage_state else ""
        if storage_state:
            try:
                self._profiles.save(service, storage_state)
            except ValueError:
                pass  # service name unsafe — profile not saved, account still vaulted

        self._vault.store(
            service=service, email=email_addr, password=password,
            cookies_json=cookies_json, notes=notes,
        )
        return {"status": "live", "service": service, "email": email_addr, "url": signup_url}

    async def get_account(self, *, service: str, email: str) -> dict[str, Any] | None:
        rec = self._vault.get(service=service, email=email)
        if rec is None:
            return None
        return {
            "service": rec.service, "email": rec.email,
            "password": rec.password, "cookies_json": rec.cookies_json,
            "status": rec.status, "last_login_iso": rec.last_login_iso,
            "notes": rec.notes,
        }

    async def list_accounts(self, *, status: str | None = None) -> list[dict[str, Any]]:
        rows = self._vault.list_accounts(status=status)
        return [
            {"service": r.service, "email": r.email, "password": r.password,
             "cookies_json": r.cookies_json, "status": r.status,
             "last_login_iso": r.last_login_iso, "notes": r.notes}
            for r in rows
        ]

    async def mark_zombie(
        self, *, service: str, email: str, reason: str,
    ) -> dict[str, Any]:
        self._vault.mark_zombie(service=service, email=email, reason=reason)
        return {"service": service, "email": email, "status": "zombie", "reason": reason}

    async def _poll_verification(self, alias: str) -> Any:
        deadline = asyncio.get_event_loop().time() + self._verify_timeout
        while asyncio.get_event_loop().time() < deadline:
            result = await self._email_reader.find_verification(
                alias=alias, since_minutes=10,
            )
            if result is not None:
                return result
            await asyncio.sleep(self._verify_interval)
        return None

    @staticmethod
    def _extract_storage_state(browser_output: str) -> dict[str, Any] | None:
        """browser-use may return free-form text or JSON. Best-effort extract."""
        import json as _json
        try:
            parsed = _json.loads(browser_output)
            if isinstance(parsed, dict) and "storage_state" in parsed:
                state = parsed["storage_state"]
                return state if isinstance(state, dict) else None
            return parsed if isinstance(parsed, dict) and "cookies" in parsed else None
        except _json.JSONDecodeError:
            return None
```

- [ ] **Step 4: Update make_live_ctx signature + body**

In `src/clawbot/skill_ctx.py`, in `make_live_ctx`, add the new parameters and wire `_LiveAccounts`. The full updated signature and body:

```python
def make_live_ctx(
    *,
    caller_id: str,
    budget_usd: float,
    llm_pool: Any,
    bus: Any,
    brain: Any,
    db_pool: Any,
    escalation: Any,
    secret_allowlist: list[str],
    workspace_root: str,
    fs_allowed_roots: list[str] | None = None,
    stripe_secret_key: str = "",
    x_bearer: str = "",
    linkedin_token: str = "",
    reddit_creds: dict[str, str] | None = None,
    resend_api_key: str = "",
    email_from_address: str = "",
    bouncer_api_key: str = "",
    tavily_api_key: str = "",
    firecrawl_api_key: str = "",
    accounts_vault_key: str = "",
    accounts_db_path: str = "data/accounts.db",
    imap_host: str = "",
    imap_port: int = 993,
    imap_user: str = "",
    imap_password: str = "",
    email_domain: str = "",
) -> SkillCtx:
    """Build a SkillCtx wired to live services. ..."""
    extra_roots = fs_allowed_roots or []
    payments: PaymentsClient = (
        _LivePayments(stripe_secret_key) if stripe_secret_key else _NoopPayments()
    )
    social: SocialClient = (
        _LiveSocial(x_bearer, linkedin_token, reddit_creds)
        if (x_bearer or linkedin_token or reddit_creds)
        else _NoopSocial()
    )
    email: EmailClient = (
        _LiveEmail(resend_api_key, email_from_address, bouncer_api_key)
        if resend_api_key
        else _NoopEmail()
    )
    search: SearchClient = (
        _LiveSearch(tavily_api_key, firecrawl_api_key)
        if (tavily_api_key or firecrawl_api_key)
        else _NoopSearch()
    )
    # Single _LiveBrowser shared by SkillCtx.browser and _LiveAccounts so the
    # CX21's 4GB RAM cap is honoured — two instances would double the concurrent
    # Chromium ceiling (2 each → 4 total) and oom the container.
    browser_client = _LiveBrowser(pool=llm_pool)

    # Accounts requires vault + IMAP + domain all configured; otherwise noop.
    accounts: AccountsClient
    if accounts_vault_key and imap_host and email_domain:
        from clawbot.accounts_store import AccountsStore
        from clawbot.profile_store import ProfileStore
        from clawbot.email_reader import EmailReader
        vault = AccountsStore(db_path=accounts_db_path, encryption_key=accounts_vault_key)
        vault.init_schema()
        profiles = ProfileStore(root="data/profiles")
        email_reader = EmailReader(
            host=imap_host, port=imap_port,
            user=imap_user, password=imap_password,
            domain=email_domain,
        )
        accounts = _LiveAccounts(
            vault=vault, profiles=profiles,
            browser=browser_client, email_reader=email_reader,
            email_domain=email_domain,
        )
    else:
        accounts = _NoopAccounts()

    return SkillCtx(
        http=_LiveHttp(),
        sql=_LiveSql(db_pool),
        llm=_LiveLlm(llm_pool, caller_id),
        vector=_LiveVector(brain, caller_id),
        secret=_LiveSecret(secret_allowlist),
        fs=_LiveFs(workspace_root, extra_roots),
        time=_LiveTime(),
        operator=_LiveOperator(escalation, bus, caller_id),
        bus=_LiveBus(bus, caller_id),
        log=_LiveLog(caller_id),
        browser=browser_client,
        payments=payments,
        social=social,
        email=email,
        search=search,
        accounts=accounts,
        caller_id=caller_id,
        budget_usd=budget_usd,
    )
```

- [ ] **Step 5: Update directive_router to pass the new keys**

In `src/clawbot/directive_router.py`, in `_handle_skill_call`, extend the `make_live_ctx` call. Locate the existing block and add the new keyword args at the bottom of the call:

```python
        ctx = make_live_ctx(
            caller_id=from_agent,
            budget_usd=0.10,
            llm_pool=getattr(self._factory, "_pool", None),
            bus=self._bus,
            brain=self._brain,
            db_pool=getattr(self, "_db_pool", None),
            escalation=None,
            secret_allowlist=[
                "GUMROAD_API_KEY", "STRIPE_SECRET_KEY",
                "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
                "STRIPE_ISSUING_CARDHOLDER_ID",  # CFO reads via secret_get → passes to stripe_issue_card
            ],
            workspace_root=str(self._metrics_dir / "workspace"),
            fs_allowed_roots=[
                str(self._metrics_dir.parent / "agents" / "skills"),
                str(self._metrics_dir.parent / "agents" / "workers"),
                str(self._metrics_dir.parent / "data"),
            ],
            tavily_api_key=settings.tavily_api_key,
            firecrawl_api_key=settings.firecrawl_api_key,
            accounts_vault_key=settings.accounts_vault_key,
            accounts_db_path=settings.accounts_db_path,
            imap_host=settings.imap_host,
            imap_port=settings.imap_port,
            imap_user=settings.imap_user,
            imap_password=settings.imap_password,
            email_domain=settings.email_domain,
        )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_accounts_ctx.py tests/test_accounts_store.py tests/test_email_reader.py tests/test_profile_store.py tests/test_stripe_issuing.py tests/test_search_ctx.py -v`
Expected: all passing (4 new live-orchestrator tests + earlier 9 + 6 + 4 + 5 + 6 + 8).

- [ ] **Step 7: Commit**

```bash
git add src/clawbot/skill_ctx.py src/clawbot/directive_router.py tests/test_accounts_ctx.py
git commit -m "feat: _LiveAccounts orchestrator wires vault + IMAP + browser into SkillCtx"
```

---

## Task 8: Builtin skills for account management

**Files:**
- Create: `agents/skills/_builtin/accounts/create.py`
- Create: `agents/skills/_builtin/accounts/get.py`
- Create: `agents/skills/_builtin/accounts/list.py`
- Create: `agents/skills/_builtin/accounts/mark_zombie.py`
- Create: `tests/test_builtin_accounts.py`
- Modify: `tests/test_builtin_skills.py` (extend `EXPECTED_BUILTINS`)

Skills are intentionally tiny — they delegate to `ctx.accounts.*`. The registry validates `returns` matches META, so the dicts returned must contain exactly the documented keys.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_builtin_accounts.py`:

```python
"""Builtin account-management skills route through ctx.accounts.*"""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

from clawbot.skill_registry import SkillRegistry
from clawbot.skill_ctx import make_noop_ctx

BUILTIN_DIR = Path(__file__).parent.parent / "agents" / "skills" / "_builtin"


def _registry() -> SkillRegistry:
    reg = SkillRegistry(skills_dir=BUILTIN_DIR)
    reg.discover()
    return reg


def test_account_create_skill_routes_to_ctx():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="cmo", budget_usd=0.10)
    ctx.accounts.create_account = AsyncMock(return_value={
        "status": "live", "service": "substack",
        "email": "substack-1@example.com", "url": "https://substack.com/signup",
    })
    record = asyncio.run(reg.call("account_create", {
        "service": "substack", "signup_url": "https://substack.com/signup",
    }, ctx))
    assert record.ok is True
    assert record.result["status"] == "live"
    ctx.accounts.create_account.assert_called_once()


def test_account_get_skill_returns_creds_when_present():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="cmo", budget_usd=0.10)
    ctx.accounts.get_account = AsyncMock(return_value={
        "service": "s", "email": "e@x.com", "password": "p",
        "cookies_json": "{}", "status": "live",
        "last_login_iso": "2026-01-01T00:00:00+00:00", "notes": "",
    })
    record = asyncio.run(reg.call("account_get", {
        "service": "s", "email": "e@x.com",
    }, ctx))
    assert record.ok is True
    assert record.result["password"] == "p"


def test_account_get_skill_returns_not_found_dict_for_missing():
    """Skill returns dict with 'found': False rather than None — registry rejects None."""
    reg = _registry()
    ctx = make_noop_ctx(caller_id="cmo", budget_usd=0.10)
    ctx.accounts.get_account = AsyncMock(return_value=None)
    record = asyncio.run(reg.call("account_get", {
        "service": "missing", "email": "no@x.com",
    }, ctx))
    assert record.ok is True
    assert record.result["found"] is False


def test_account_list_skill_returns_count_and_items():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="cmo", budget_usd=0.10)
    ctx.accounts.list_accounts = AsyncMock(return_value=[
        {"service": "a", "email": "a@x.com", "password": "p1",
         "cookies_json": "", "status": "live",
         "last_login_iso": "x", "notes": ""},
    ])
    record = asyncio.run(reg.call("account_list", {"status": "live"}, ctx))
    assert record.ok is True
    assert record.result["count"] == 1
    assert len(record.result["accounts"]) == 1


def test_account_mark_zombie_skill_passes_reason():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="cmo", budget_usd=0.10)
    ctx.accounts.mark_zombie = AsyncMock(return_value={
        "service": "x", "email": "e@x.com", "status": "zombie", "reason": "stuck",
    })
    record = asyncio.run(reg.call("account_mark_zombie", {
        "service": "x", "email": "e@x.com", "reason": "stuck",
    }, ctx))
    assert record.ok is True
    assert record.result["status"] == "zombie"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_builtin_accounts.py -v`
Expected: `unknown skill: account_create` errors — skills don't exist yet.

- [ ] **Step 3: Create the four builtin skills**

Create `agents/skills/_builtin/accounts/create.py`:

```python
META = {
    "name": "account_create", "builtin": True,
    "description": "Autonomously sign up for a service using catch-all email + vault. "
                   "Returns status=live on success or status=zombie if signup got stuck.",
    "params": {"service": "str", "signup_url": "str", "notes": "str"},
    "returns": {"status": "str", "service": "str", "email": "str"},
    "cost_estimate_usd": 0.05, "timeout_s": 180.0,
}


async def run(ctx, service: str, signup_url: str, notes: str = "") -> dict:
    result = await ctx.accounts.create_account(
        service=service, signup_url=signup_url, notes=notes,
    )
    return {
        "status": result.get("status", "unknown"),
        "service": result.get("service", service),
        "email": result.get("email", ""),
    }
```

Create `agents/skills/_builtin/accounts/get.py`:

```python
META = {
    "name": "account_get", "builtin": True,
    "description": "Fetch creds for one (service, email) account from the vault. "
                   "Returns found=False if no such account.",
    "params": {"service": "str", "email": "str"},
    "returns": {"found": "bool", "service": "str", "email": "str",
                "password": "str", "cookies_json": "str", "status": "str"},
    "cost_estimate_usd": 0.0, "timeout_s": 5.0,
}


async def run(ctx, service: str, email: str) -> dict:
    rec = await ctx.accounts.get_account(service=service, email=email)
    if rec is None:
        return {
            "found": False, "service": service, "email": email,
            "password": "", "cookies_json": "", "status": "missing",
        }
    return {
        "found": True,
        "service": rec["service"], "email": rec["email"],
        "password": rec["password"], "cookies_json": rec["cookies_json"],
        "status": rec["status"],
    }
```

Create `agents/skills/_builtin/accounts/list.py`:

```python
META = {
    "name": "account_list", "builtin": True,
    "description": "List all vaulted accounts, optionally filtered by status (live|zombie|revoked).",
    "params": {"status": "str"},
    "returns": {"count": "int", "accounts": "list"},
    "cost_estimate_usd": 0.0, "timeout_s": 5.0,
}


async def run(ctx, status: str = "") -> dict:
    rows = await ctx.accounts.list_accounts(status=status or None)
    return {"count": len(rows), "accounts": rows}
```

Create `agents/skills/_builtin/accounts/mark_zombie.py`:

```python
META = {
    "name": "account_mark_zombie", "builtin": True,
    "description": "Mark an account as zombie (manual intervention needed). "
                   "Use when a service-side issue prevents normal recovery.",
    "params": {"service": "str", "email": "str", "reason": "str"},
    "returns": {"service": "str", "email": "str", "status": "str"},
    "cost_estimate_usd": 0.0, "timeout_s": 5.0,
}


async def run(ctx, service: str, email: str, reason: str) -> dict:
    result = await ctx.accounts.mark_zombie(
        service=service, email=email, reason=reason,
    )
    return {
        "service": result["service"], "email": result["email"],
        "status": result["status"],
    }
```

- [ ] **Step 4: Add skill names to test_builtin_skills.py EXPECTED_BUILTINS**

In `tests/test_builtin_skills.py`, update the `EXPECTED_BUILTINS` set to include the new skill names. The full block:

```python
EXPECTED_BUILTINS = {
    "http_fetch", "http_post", "llm_complete", "vector_search", "vector_write",
    "secret_get", "fs_read", "fs_write", "fs_list", "sql_query",
    "operator_message", "operator_request_approval", "time_now", "bus_publish",
    "worker_spawn", "worker_fire", "skill_request",
    "account_create", "account_get", "account_list", "account_mark_zombie",
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_builtin_accounts.py tests/test_builtin_skills.py -v`
Expected: 5 new pass + existing builtin tests still green.

- [ ] **Step 6: Commit**

```bash
git add agents/skills/_builtin/accounts/ tests/test_builtin_accounts.py tests/test_builtin_skills.py
git commit -m "feat: account_create/get/list/mark_zombie builtin skills"
```

---

## Task 9: Builtin skills for Stripe Issuing

**Files:**
- Create: `agents/skills/_builtin/payments/stripe_issue_card.py`
- Create: `agents/skills/_builtin/payments/stripe_freeze_card.py`
- Create: `agents/skills/_builtin/payments/stripe_list_authorizations.py`
- Create: `tests/test_builtin_payments_issuing.py`
- Modify: `tests/test_builtin_skills.py` (extend `EXPECTED_BUILTINS`)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_builtin_payments_issuing.py`:

```python
"""Builtin Stripe Issuing skills."""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

from clawbot.skill_registry import SkillRegistry
from clawbot.skill_ctx import make_noop_ctx

BUILTIN_DIR = Path(__file__).parent.parent / "agents" / "skills" / "_builtin"


def _registry() -> SkillRegistry:
    reg = SkillRegistry(skills_dir=BUILTIN_DIR)
    reg.discover()
    return reg


def test_stripe_issue_card_routes_to_payments():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="cfo", budget_usd=0.10)
    ctx.payments.issue_card = AsyncMock(return_value={
        "id": "ic_abc", "last4": "4242", "exp_month": 12,
        "exp_year": 2028, "status": "active", "cardholder": "ich_x",
    })
    record = asyncio.run(reg.call("stripe_issue_card", {
        "cardholder_id": "ich_x", "daily_limit_usd": 25, "agent_id": "cmo",
    }, ctx))
    assert record.ok is True
    assert record.result["id"] == "ic_abc"
    assert record.result["last4"] == "4242"


def test_stripe_freeze_card_routes_to_payments():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="cfo", budget_usd=0.10)
    ctx.payments.freeze_card = AsyncMock(return_value={
        "id": "ic_x", "status": "canceled",
    })
    record = asyncio.run(reg.call("stripe_freeze_card", {
        "card_id": "ic_x",
    }, ctx))
    assert record.ok is True
    assert record.result["status"] == "canceled"


def test_stripe_list_authorizations_returns_count():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="cfo", budget_usd=0.10)
    ctx.payments.list_authorizations = AsyncMock(return_value=[
        {"id": "iauth_1", "amount": 500, "merchant_data": {"name": "Substack"}},
        {"id": "iauth_2", "amount": 1200, "merchant_data": {"name": "Mailgun"}},
    ])
    record = asyncio.run(reg.call("stripe_list_authorizations", {
        "card_id": "ic_x", "limit": 10,
    }, ctx))
    assert record.ok is True
    assert record.result["count"] == 2
    assert len(record.result["authorizations"]) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_builtin_payments_issuing.py -v`
Expected: `unknown skill: stripe_issue_card`.

- [ ] **Step 3: Create the three Issuing skills**

Create `agents/skills/_builtin/payments/stripe_issue_card.py`:

```python
META = {
    "name": "stripe_issue_card", "builtin": True,
    "description": "Issue a virtual Stripe card for an agent with a daily spend limit (USD). "
                   "Returns card id + last4 + expiry. Agent uses these via browser-use to checkout.",
    "params": {"cardholder_id": "str", "daily_limit_usd": "int", "agent_id": "str"},
    "returns": {"id": "str", "last4": "str", "exp_month": "int",
                "exp_year": "int", "status": "str"},
    "cost_estimate_usd": 0.0, "timeout_s": 15.0, "requires_approval": True,
}


async def run(ctx, cardholder_id: str, daily_limit_usd: int, agent_id: str) -> dict:
    card = await ctx.payments.issue_card(
        cardholder_id=cardholder_id,
        daily_limit_usd=daily_limit_usd,
        agent_id=agent_id,
    )
    return {
        "id": card["id"], "last4": card["last4"],
        "exp_month": card["exp_month"], "exp_year": card["exp_year"],
        "status": card["status"],
    }
```

Create `agents/skills/_builtin/payments/stripe_freeze_card.py`:

```python
META = {
    "name": "stripe_freeze_card", "builtin": True,
    "description": "Cancel a Stripe Issuing card permanently. Use for compromised or "
                   "decommissioned agent cards.",
    "params": {"card_id": "str"},
    "returns": {"id": "str", "status": "str"},
    "cost_estimate_usd": 0.0, "timeout_s": 10.0,
}


async def run(ctx, card_id: str) -> dict:
    result = await ctx.payments.freeze_card(card_id=card_id)
    return {"id": result["id"], "status": result["status"]}
```

Create `agents/skills/_builtin/payments/stripe_list_authorizations.py`:

```python
META = {
    "name": "stripe_list_authorizations", "builtin": True,
    "description": "List recent card-spend authorizations. Returns count and the list. "
                   "Use to audit what an agent actually spent money on.",
    "params": {"card_id": "str", "limit": "int"},
    "returns": {"count": "int", "authorizations": "list"},
    "cost_estimate_usd": 0.0, "timeout_s": 10.0,
}


async def run(ctx, card_id: str, limit: int = 20) -> dict:
    auths = await ctx.payments.list_authorizations(card_id=card_id, limit=limit)
    return {"count": len(auths), "authorizations": auths}
```

- [ ] **Step 4: Add the new skill names to EXPECTED_BUILTINS**

In `tests/test_builtin_skills.py`, extend `EXPECTED_BUILTINS`:

```python
EXPECTED_BUILTINS = {
    "http_fetch", "http_post", "llm_complete", "vector_search", "vector_write",
    "secret_get", "fs_read", "fs_write", "fs_list", "sql_query",
    "operator_message", "operator_request_approval", "time_now", "bus_publish",
    "worker_spawn", "worker_fire", "skill_request",
    "account_create", "account_get", "account_list", "account_mark_zombie",
    "stripe_issue_card", "stripe_freeze_card", "stripe_list_authorizations",
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_builtin_payments_issuing.py tests/test_builtin_skills.py -v`
Expected: 3 new pass + existing green.

- [ ] **Step 6: Commit**

```bash
git add agents/skills/_builtin/payments/stripe_issue_card.py agents/skills/_builtin/payments/stripe_freeze_card.py agents/skills/_builtin/payments/stripe_list_authorizations.py tests/test_builtin_payments_issuing.py tests/test_builtin_skills.py
git commit -m "feat: stripe_issue_card/freeze_card/list_authorizations builtin skills"
```

---

## Task 10: Full suite + operator setup documentation

**Files:**
- Modify: `C:\ClaudeShared\memory\projects\clawbot\operating_facts.md`

End-to-end sanity check and operator runbook update.

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest --tb=short`
Expected: 450+ tests pass; the only failures are the pre-existing 2 asyncpg local-env failures (documented in `operating_facts.md`).

- [ ] **Step 2: Document operator setup steps in operating_facts.md**

Edit `C:\ClaudeShared\memory\projects\clawbot\operating_facts.md`, append at the bottom:

```markdown

## Autonomous account management (added 2026-05-17)

Three operator-side prerequisites before _LiveAccounts and Stripe Issuing become active:

### Email infrastructure (one-time setup)
1. Buy a domain (~$10/yr). Cloudflare Registrar sells at cost.
2. In Cloudflare dashboard → Email → Email Routing → enable; set catch-all
   `*@yourdomain.com` to forward to a Gmail inbox you control.
3. Generate a Gmail App Password (Google Account → Security → App Passwords).
4. Add to `/opt/clawbot/.env`:
   ```
   EMAIL_DOMAIN=yourdomain.com
   IMAP_HOST=imap.gmail.com
   IMAP_PORT=993
   IMAP_USER=your.gmail@gmail.com
   IMAP_PASSWORD=<app password from step 3>
   ```

### Vault key (one-time setup)
1. Generate: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
2. Add to `.env`: `ACCOUNTS_VAULT_KEY=<output from step 1>`
3. KEEP THIS KEY. Losing it makes the vault unreadable forever.

### Stripe Issuing (one-time setup)
1. In Stripe dashboard → Issuing → Get started. Complete KYB (clawbot is UK Ltd).
2. Fund the Stripe balance from your UK business bank (Stripe → Balance → Top up).
3. Create one company-type cardholder representing clawbot itself.
4. Copy the cardholder ID (`ich_...`).
5. Add to `.env`: `STRIPE_ISSUING_CARDHOLDER_ID=ich_xxx`

### Redeploy after setup
```bash
ssh clawbot "cd /opt/clawbot && git pull && docker compose up -d --build"
```
Image rebuild is required because `cryptography` is a new pip dep.
```

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/plans/2026-05-17-autonomous-account-management.md
git commit -m "docs: autonomous account management plan + operator setup runbook"
```

---

## Acceptance Criteria (binary — all must pass, then stop)

- [ ] `uv run pytest` shows ≥ (previous count) + the new test count, with only the 2 pre-existing asyncpg failures
- [ ] `tests/test_builtin_skills.py::test_all_expected_builtins_load` passes with the 7 new skill names
- [ ] With `ACCOUNTS_VAULT_KEY` unset, `make_live_ctx` returns a SkillCtx whose `accounts` is `_NoopAccounts` (no exception)
- [ ] With all `.env` keys set, `make_live_ctx` returns a SkillCtx whose `accounts` is `_LiveAccounts` and the vault DB is created on first call
- [ ] No new pyright errors beyond the pre-existing local-only ones (asyncpg, pgvector unresolved)
- [ ] All commits compile; each commit is self-contained
- [ ] Operator runbook in `operating_facts.md` lists exactly which `.env` keys are required

When all pass: done. Do not invent new criteria.
