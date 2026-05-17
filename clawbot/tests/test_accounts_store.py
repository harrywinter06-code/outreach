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
