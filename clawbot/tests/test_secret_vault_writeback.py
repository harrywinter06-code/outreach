"""Z4 — vault-backed secret set/get + lookup hierarchy tests.

Covers:
- AccountsStore.set_secret + get_secret round-trip with Fernet encryption
- _LiveSecret.get prefers vault over env (so agent-set credentials shadow
  unset env vars without container restart)
- _LiveSecret.set requires allowlisted name
- _NoopSecret silently no-ops
"""
import os
import tempfile
from pathlib import Path
from cryptography.fernet import Fernet

import pytest


def _make_store():
    """Build an AccountsStore with a temp SQLite + fresh Fernet key."""
    from clawbot.accounts_store import AccountsStore
    tmpdir = tempfile.mkdtemp()
    db = str(Path(tmpdir) / "vault.db")
    key = Fernet.generate_key().decode()
    store = AccountsStore(db_path=db, encryption_key=key)
    store.init_schema()
    store.init_secrets_schema()
    return store


def test_set_and_get_secret_roundtrip():
    store = _make_store()
    store.set_secret(name="DEVTO_API_KEY", value="real_token_xyz")
    assert store.get_secret("DEVTO_API_KEY") == "real_token_xyz"


def test_get_secret_returns_none_for_unset():
    store = _make_store()
    assert store.get_secret("NEVER_SET") is None


def test_set_secret_overwrites_existing_value():
    store = _make_store()
    store.set_secret(name="X", value="old")
    store.set_secret(name="X", value="new")
    assert store.get_secret("X") == "new"


def test_set_secret_rejects_invalid_name():
    store = _make_store()
    with pytest.raises(ValueError, match="invalid"):
        store.set_secret(name="bad=name", value="v")
    with pytest.raises(ValueError, match="invalid"):
        store.set_secret(name="bad\nname", value="v")
    with pytest.raises(ValueError, match="invalid"):
        store.set_secret(name="", value="v")


def test_list_secret_names_does_not_leak_values():
    store = _make_store()
    store.set_secret(name="A", value="secret_a")
    store.set_secret(name="B", value="secret_b")
    names = store.list_secret_names()
    assert names == ["A", "B"]
    # The values themselves never leave the store via this method
    for n in names:
        assert n in ("A", "B")  # only names returned


def test_secret_values_encrypted_at_rest():
    """A SQLite row dump must NOT show the plaintext — defends against
    DB backups / container exfil."""
    import sqlite3
    store = _make_store()
    store.set_secret(name="LEAK_TEST", value="plaintext_password_123")
    with sqlite3.connect(store._db_path) as conn:
        row = conn.execute(
            "SELECT value_enc FROM agent_secrets WHERE name='LEAK_TEST'",
        ).fetchone()
    raw = row[0]
    assert b"plaintext_password_123" not in raw, "value stored as plaintext"


def test_live_secret_prefers_vault_over_env(monkeypatch):
    """The whole point of the writeback: a vault-set credential shadows
    an env var of the same name. After account_extract_api_key writes
    BSKY_APP_PASSWORD, the next bluesky_post call gets the vault value
    even if no .env update happened."""
    from clawbot.skill_ctx import _LiveSecret
    store = _make_store()
    store.set_secret(name="BSKY_APP_PASSWORD", value="vault_value")
    monkeypatch.setenv("BSKY_APP_PASSWORD", "env_value")
    secret = _LiveSecret(allowlist=["BSKY_APP_PASSWORD"], vault=store)
    assert secret.get("BSKY_APP_PASSWORD") == "vault_value"


def test_live_secret_falls_back_to_env_when_vault_unset():
    from clawbot.skill_ctx import _LiveSecret
    store = _make_store()
    # Don't write to vault
    os.environ["FALLBACK_TEST"] = "env_only"
    try:
        secret = _LiveSecret(allowlist=["FALLBACK_TEST"], vault=store)
        assert secret.get("FALLBACK_TEST") == "env_only"
    finally:
        del os.environ["FALLBACK_TEST"]


def test_live_secret_falls_back_to_env_when_no_vault():
    """make_live_ctx without ACCOUNTS_VAULT_KEY → vault=None → env-only."""
    from clawbot.skill_ctx import _LiveSecret
    os.environ["NO_VAULT_TEST"] = "env_value"
    try:
        secret = _LiveSecret(allowlist=["NO_VAULT_TEST"], vault=None)
        assert secret.get("NO_VAULT_TEST") == "env_value"
    finally:
        del os.environ["NO_VAULT_TEST"]


def test_live_secret_set_requires_allowlist():
    """Agent can only set secrets it's allowed to set — defends against
    the agent accidentally writing arbitrary names to the vault."""
    from clawbot.skill_ctx import _LiveSecret
    store = _make_store()
    secret = _LiveSecret(allowlist=["DEVTO_API_KEY"], vault=store)
    secret.set("DEVTO_API_KEY", "ok")  # allowlisted: succeeds
    assert store.get_secret("DEVTO_API_KEY") == "ok"
    with pytest.raises(PermissionError, match="not allowlisted"):
        secret.set("RANDOM_KEY", "should_not_persist")
    assert store.get_secret("RANDOM_KEY") is None


def test_live_secret_set_without_vault_is_silent_noop_with_warning():
    """No vault wired (e.g. ACCOUNTS_VAULT_KEY unset) → set() doesn't crash
    but also doesn't persist. Logged warning is the operator's signal."""
    from clawbot.skill_ctx import _LiveSecret
    secret = _LiveSecret(allowlist=["X"], vault=None)
    secret.set("X", "ignored")  # no exception
    assert secret.get("X") == ""  # nothing came back


def test_noop_secret_set_is_silent_noop():
    """make_noop_ctx scenarios — set() is a no-op without error."""
    from clawbot.skill_ctx import _NoopSecret
    s = _NoopSecret()
    s.set("ANYTHING", "value")  # no exception
    assert s.get("ANYTHING") == ""
