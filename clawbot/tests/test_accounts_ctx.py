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
    assert "accounts" in SkillCtx.__dataclass_fields__


def test_shadow_ctx_has_accounts_field():
    from clawbot.shadow_ctx import make_shadow_ctx
    ctx = make_shadow_ctx(caller_id="t", budget_usd=0)
    assert hasattr(ctx, "accounts")
    assert asyncio.run(ctx.accounts.list_accounts(status="live")) == []


def test_live_accounts_creates_signup_and_stores_creds(tmp_path):
    """Happy path: signup task succeeds, email arrives, creds vault'd."""
    from unittest.mock import AsyncMock
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
