"""ops CLI — operator credential management tests.

Covers:
- add-account: per-service correct secret names land in vault
- add-account: unknown service errors out
- add-account: too many values errors out
- list-accounts: shows per-service completeness
- remove-account: removes the right secrets
- '-' value triggers getpass prompt
"""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet


@pytest.fixture
def temp_vault(monkeypatch):
    """Point ops_cli at a fresh temp vault for the duration of the test."""
    key = Fernet.generate_key().decode()
    tmpdir = tempfile.mkdtemp()
    db = str(Path(tmpdir) / "vault.db")
    monkeypatch.setenv("ACCOUNTS_VAULT_KEY", key)
    monkeypatch.setenv("ACCOUNTS_DB_PATH", db)
    yield db


def test_add_bluesky_stores_both_secrets(temp_vault):
    from clawbot.ops_cli import main
    from clawbot.accounts_store import AccountsStore
    rc = main(["add-account", "bluesky", "handle.bsky.social", "abcd-efgh-ijkl-mnop"])
    assert rc == 0
    store = AccountsStore(db_path=temp_vault, encryption_key=os.environ["ACCOUNTS_VAULT_KEY"])
    assert store.get_secret("BSKY_HANDLE") == "handle.bsky.social"
    assert store.get_secret("BSKY_APP_PASSWORD") == "abcd-efgh-ijkl-mnop"


def test_add_devto_stores_single_secret(temp_vault):
    from clawbot.ops_cli import main
    from clawbot.accounts_store import AccountsStore
    rc = main(["add-account", "devto", "fake_api_key_xyz"])
    assert rc == 0
    store = AccountsStore(db_path=temp_vault, encryption_key=os.environ["ACCOUNTS_VAULT_KEY"])
    assert store.get_secret("DEVTO_API_KEY") == "fake_api_key_xyz"


def test_add_hashnode_stores_both_pat_and_publication(temp_vault):
    from clawbot.ops_cli import main
    from clawbot.accounts_store import AccountsStore
    rc = main(["add-account", "hashnode", "pat_xxx", "111122223333444455556666"])
    assert rc == 0
    store = AccountsStore(db_path=temp_vault, encryption_key=os.environ["ACCOUNTS_VAULT_KEY"])
    assert store.get_secret("HASHNODE_PAT") == "pat_xxx"
    assert store.get_secret("HASHNODE_PUBLICATION_ID") == "111122223333444455556666"


def test_add_unknown_service_errors(temp_vault, capsys):
    from clawbot.ops_cli import main
    rc = main(["add-account", "facebook", "x", "y"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "unknown service" in err


def test_add_too_many_values_errors(temp_vault, capsys):
    """devto wants 1 value; supplying 3 is an operator typo we should catch."""
    from clawbot.ops_cli import main
    rc = main(["add-account", "devto", "a", "b", "c"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "too many values" in err


def test_add_marks_accounts_table_row(temp_vault):
    """add-account writes an `accounts` row so list_accounts in the ctx
    can show operator-provided accounts alongside agent-created ones."""
    from clawbot.ops_cli import main
    from clawbot.accounts_store import AccountsStore
    main(["add-account", "devto", "key123"])
    store = AccountsStore(db_path=temp_vault, encryption_key=os.environ["ACCOUNTS_VAULT_KEY"])
    rows = store.list_accounts(status="live")
    matching = [r for r in rows if r.service == "devto"]
    assert len(matching) == 1
    assert matching[0].email.startswith("operator-provided")
    assert "operator" in matching[0].notes.lower()


def test_dash_value_prompts_via_getpass(temp_vault, monkeypatch):
    """'-' as a value triggers interactive prompt — keeps secrets out of
    shell history."""
    from clawbot.ops_cli import main
    from clawbot.accounts_store import AccountsStore
    inputs = iter(["clawbot.bsky.social", "secret-from-prompt"])
    monkeypatch.setattr("getpass.getpass", lambda _: next(inputs))
    rc = main(["add-account", "bluesky", "-", "-"])
    assert rc == 0
    store = AccountsStore(db_path=temp_vault, encryption_key=os.environ["ACCOUNTS_VAULT_KEY"])
    assert store.get_secret("BSKY_APP_PASSWORD") == "secret-from-prompt"


def test_empty_value_after_prompt_aborts(temp_vault, monkeypatch, capsys):
    """If operator hits enter on the prompt, don't silently store empty."""
    from clawbot.ops_cli import main
    monkeypatch.setattr("getpass.getpass", lambda _: "")
    rc = main(["add-account", "devto", "-"])
    assert rc == 2
    assert "empty value" in capsys.readouterr().err.lower()


def test_list_accounts_shows_complete_and_incomplete(temp_vault, capsys):
    from clawbot.ops_cli import main
    main(["add-account", "devto", "k1"])
    main(["add-account", "bluesky", "h", "p"])
    # mastodon NOT added — should show incomplete
    capsys.readouterr()  # drain previous output
    rc = main(["list-accounts"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "BSKY_HANDLE" in out
    assert "DEVTO_API_KEY" in out
    # mastodon section shows missing
    assert "mastodon" in out
    assert "MISSING" in out


def test_remove_account_clears_vault_secrets(temp_vault):
    from clawbot.ops_cli import main
    from clawbot.accounts_store import AccountsStore
    main(["add-account", "bluesky", "h", "p"])
    rc = main(["remove-account", "bluesky"])
    assert rc == 0
    store = AccountsStore(db_path=temp_vault, encryption_key=os.environ["ACCOUNTS_VAULT_KEY"])
    assert store.get_secret("BSKY_HANDLE") is None
    assert store.get_secret("BSKY_APP_PASSWORD") is None


def test_secret_is_readable_via_live_secret_after_cli_add(temp_vault):
    """End-to-end: secret added via CLI is visible to _LiveSecret.get
    (which is what publishing skills call). This is the whole point —
    skill cycles pick it up on next run, no restart."""
    from clawbot.ops_cli import main
    from clawbot.skill_ctx import _LiveSecret
    from clawbot.accounts_store import AccountsStore
    main(["add-account", "devto", "key_for_skill"])
    store = AccountsStore(db_path=temp_vault, encryption_key=os.environ["ACCOUNTS_VAULT_KEY"])
    secret = _LiveSecret(allowlist=["DEVTO_API_KEY"], vault=store)
    assert secret.get("DEVTO_API_KEY") == "key_for_skill"


def test_missing_vault_key_errors_clearly(monkeypatch, capsys):
    """If ACCOUNTS_VAULT_KEY isn't set anywhere, operator gets a clear
    error pointing them at the VPS wrapper."""
    from clawbot.ops_cli import main
    monkeypatch.delenv("ACCOUNTS_VAULT_KEY", raising=False)
    monkeypatch.delenv("ACCOUNTS_DB_PATH", raising=False)
    # Make settings.accounts_vault_key also empty
    with patch("clawbot.config.settings") as fake_settings:
        fake_settings.accounts_vault_key = ""
        fake_settings.accounts_db_path = "/tmp/x.db"
        with pytest.raises(SystemExit) as exc:
            main(["add-account", "devto", "k"])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "ACCOUNTS_VAULT_KEY" in err
