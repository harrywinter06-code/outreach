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
            conn.execute("PRAGMA journal_mode=WAL")
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
        """Mark an account as zombie. Appends `reason` to existing notes
        (preserves operator annotations) and raises KeyError if the row
        does not exist (silent no-ops on typos are a footgun)."""
        with sqlite3.connect(self._db_path) as conn:
            cur = conn.execute(
                """
                UPDATE accounts
                   SET status='zombie',
                       notes = CASE
                           WHEN notes = '' THEN ?
                           ELSE notes || ' | ' || ?
                       END
                 WHERE service=? AND email=?
                """,
                (reason, reason, service, email),
            )
            if cur.rowcount == 0:
                raise KeyError(f"no account for ({service!r}, {email!r})")

    def update_cookies(self, *, service: str, email: str, cookies_json: str) -> None:
        """Update cookies for an existing account; raises KeyError if absent."""
        now = datetime.now(UTC).isoformat()
        with sqlite3.connect(self._db_path) as conn:
            cur = conn.execute(
                "UPDATE accounts SET cookies_enc=?, last_login_iso=? "
                "WHERE service=? AND email=?",
                (self._enc(cookies_json), now, service, email),
            )
            if cur.rowcount == 0:
                raise KeyError(f"no account for ({service!r}, {email!r})")

    # ─── Agent-set secret store (Z4) ────────────────────────────────────────
    # Separate namespace from account credentials. Used when the agent
    # extracts an API key from a service it just signed up for (e.g. a
    # Bluesky app password) and needs to make it readable by subsequent
    # skill calls via ctx.secret.get(NAME).

    def init_secrets_schema(self) -> None:
        """Idempotent — create the agent_secrets table if missing."""
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_secrets (
                    name TEXT PRIMARY KEY,
                    value_enc BLOB NOT NULL,
                    source TEXT NOT NULL,
                    set_at TEXT NOT NULL
                )
            """)

    def set_secret(self, *, name: str, value: str, source: str = "agent") -> None:
        """Upsert an encrypted secret. `source` records who/what wrote it
        (agent / operator-import / extracted-from-<service>) for audit."""
        if not name or "=" in name or "\n" in name:
            raise ValueError(f"secret name {name!r} invalid (no '=' or newlines)")
        now = datetime.now(UTC).isoformat()
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT INTO agent_secrets (name, value_enc, source, set_at) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(name) DO UPDATE SET "
                "  value_enc=excluded.value_enc, source=excluded.source, set_at=excluded.set_at",
                (name, self._enc(value), source, now),
            )

    def get_secret(self, name: str) -> str | None:
        """Decrypt + return the secret, or None if unset."""
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT value_enc FROM agent_secrets WHERE name=?", (name,),
            ).fetchone()
        if row is None:
            return None
        return self._dec(row[0])

    def list_secret_names(self) -> list[str]:
        """Audit helper — names only, never values."""
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                "SELECT name FROM agent_secrets ORDER BY name",
            ).fetchall()
        return [r[0] for r in rows]
