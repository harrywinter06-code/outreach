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


def test_update_cookies_changes_value_and_timestamp(vault: AccountsStore):
    vault.store(service="s", email="e@x.com", password="p", cookies_json="old")
    before = vault.get(service="s", email="e@x.com")
    assert before is not None
    vault.update_cookies(service="s", email="e@x.com", cookies_json="new")
    after = vault.get(service="s", email="e@x.com")
    assert after is not None
    assert after.cookies_json == "new"
    # last_login_iso is touched by update_cookies
    assert after.last_login_iso >= before.last_login_iso


def test_update_cookies_raises_on_missing_account(vault: AccountsStore):
    with pytest.raises(KeyError, match="no account"):
        vault.update_cookies(service="missing", email="x@x.com", cookies_json="{}")


def test_mark_zombie_raises_on_missing_account(vault: AccountsStore):
    with pytest.raises(KeyError, match="no account"):
        vault.mark_zombie(service="missing", email="x@x.com", reason="r")


def test_mark_zombie_preserves_creation_notes(vault: AccountsStore):
    vault.store(service="s", email="e@x.com", password="p", cookies_json="",
                notes="created by CMO")
    vault.mark_zombie(service="s", email="e@x.com", reason="captcha failure")
    rec = vault.get(service="s", email="e@x.com")
    assert rec is not None
    assert "created by CMO" in rec.notes
    assert "captcha failure" in rec.notes
    assert rec.status == "zombie"
