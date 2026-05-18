"""Capital graduation gate + cap enforcement in _LivePayments."""
import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


def test_issue_card_raises_when_ledger_write_fails_after_stripe_success():
    """If ledger fails post-Stripe, card must be canceled and error raised."""
    from clawbot.skill_ctx import _LivePayments

    fake_ledger = MagicMock()
    fake_ledger.current_period_total_gbp = AsyncMock(return_value=Decimal("0"))
    fake_ledger.record = AsyncMock(side_effect=RuntimeError("DB down"))

    fake_card = MagicMock()
    fake_card.to_dict.return_value = {"id": "ic_failsafe", "last4": "1111",
                                       "exp_month": 1, "exp_year": 2030,
                                       "status": "active"}

    payments = _LivePayments(secret_key="sk_live_test_real",
                              capital_ledger=fake_ledger,
                              live_mode_enabled=True,
                              capital_daily_cap_gbp=Decimal("100"),
                              capital_weekly_cap_gbp=Decimal("500"))

    with patch("clawbot.skill_ctx.stripe") as stripe_mod:
        stripe_mod.issuing.Card.create.return_value = fake_card
        stripe_mod.issuing.Card.modify = MagicMock(return_value=MagicMock())
        with pytest.raises(RuntimeError, match="ledger_write_failed"):
            asyncio.run(payments.issue_card(
                cardholder_id="ich_x", daily_limit_usd=10, agent_id="cfo",
            ))
    # Card was canceled
    stripe_mod.issuing.Card.modify.assert_called_once()
    cancel_args = stripe_mod.issuing.Card.modify.call_args
    assert cancel_args[0][0] == "ic_failsafe"
    assert cancel_args.kwargs.get("status") == "canceled"


def test_rk_live_prefix_detected_as_live():
    """Restricted live keys (rk_live_) must be treated as live mode."""
    from clawbot.skill_ctx import _LivePayments
    payments = _LivePayments(secret_key="rk_live_restricted_xyz",
                              capital_ledger=None, live_mode_enabled=True,
                              capital_daily_cap_gbp=Decimal("100"),
                              capital_weekly_cap_gbp=Decimal("500"))
    assert payments._is_live_key is True


def test_capital_freeze_halts_even_in_test_mode():
    """Freeze must halt test-mode probes too."""
    from clawbot.skill_ctx import _LivePayments
    payments = _LivePayments(secret_key="sk_test_xyz",
                              capital_ledger=MagicMock(),
                              live_mode_enabled=False,
                              capital_daily_cap_gbp=Decimal("0"),
                              capital_weekly_cap_gbp=Decimal("0"),
                              capital_freeze=True)
    with pytest.raises(RuntimeError, match="capital_freeze_active"):
        asyncio.run(payments.issue_card(
            cardholder_id="ich_x", daily_limit_usd=10, agent_id="cfo",
        ))


def test_issue_card_rejects_zero_or_negative_daily_limit():
    """daily_limit_usd must be a positive int."""
    from clawbot.skill_ctx import _LivePayments
    payments = _LivePayments(secret_key="sk_test_xyz", capital_ledger=MagicMock(),
                              live_mode_enabled=False, capital_daily_cap_gbp=Decimal("0"),
                              capital_weekly_cap_gbp=Decimal("0"))
    for bad in (0, -10, 10.5, "ten"):
        with pytest.raises((ValueError, TypeError)):
            asyncio.run(payments.issue_card(
                cardholder_id="ich_x", daily_limit_usd=bad, agent_id="cfo",
            ))


def test_issue_card_succeeds_in_test_mode_regardless_of_caps():
    """Test-mode keys (sk_test_) bypass all gates."""
    from clawbot.skill_ctx import _LivePayments

    fake_ledger = MagicMock()
    fake_ledger.current_period_total_gbp = AsyncMock(return_value=Decimal("0"))
    fake_ledger.record = AsyncMock(return_value=1)

    payments = _LivePayments(secret_key="sk_test_123",
                              capital_ledger=fake_ledger,
                              live_mode_enabled=False,
                              capital_daily_cap_gbp=0,
                              capital_weekly_cap_gbp=0)

    with patch("clawbot.skill_ctx.stripe") as stripe_mod:
        fake_card = MagicMock()
        fake_card.to_dict.return_value = {"id": "ic_test", "last4": "4242",
                                           "exp_month": 12, "exp_year": 2030, "status": "active"}
        stripe_mod.issuing.Card.create.return_value = fake_card
        result = asyncio.run(payments.issue_card(
            cardholder_id="ich_x", daily_limit_usd=10, agent_id="cfo",
        ))
        assert result["id"] == "ic_test"


def test_issue_card_raises_when_live_mode_disabled_with_live_key():
    """sk_live_ + live_mode_enabled=False → raise."""
    from clawbot.skill_ctx import _LivePayments

    payments = _LivePayments(secret_key="sk_live_real",
                              capital_ledger=MagicMock(),
                              live_mode_enabled=False,
                              capital_daily_cap_gbp=Decimal("100"),
                              capital_weekly_cap_gbp=Decimal("500"))

    with pytest.raises(RuntimeError, match="live_mode_not_enabled"):
        asyncio.run(payments.issue_card(
            cardholder_id="ich_x", daily_limit_usd=10, agent_id="cfo",
        ))


def test_issue_card_raises_when_caps_not_set():
    """sk_live_ + live_mode_enabled=True + caps=0 → raise."""
    from clawbot.skill_ctx import _LivePayments

    payments = _LivePayments(secret_key="sk_live_real",
                              capital_ledger=MagicMock(),
                              live_mode_enabled=True,
                              capital_daily_cap_gbp=Decimal("0"),
                              capital_weekly_cap_gbp=Decimal("0"))

    with pytest.raises(RuntimeError, match="capital_caps_not_set"):
        asyncio.run(payments.issue_card(
            cardholder_id="ich_x", daily_limit_usd=10, agent_id="cfo",
        ))


def test_issue_card_raises_when_freeze_active():
    """capital_freeze=True halts ALL authorizations (live mode)."""
    from clawbot.skill_ctx import _LivePayments

    payments = _LivePayments(secret_key="sk_live_real",
                              capital_ledger=MagicMock(),
                              live_mode_enabled=True,
                              capital_daily_cap_gbp=Decimal("100"),
                              capital_weekly_cap_gbp=Decimal("500"),
                              capital_freeze=True)

    with pytest.raises(RuntimeError, match="capital_freeze_active"):
        asyncio.run(payments.issue_card(
            cardholder_id="ich_x", daily_limit_usd=10, agent_id="cfo",
        ))


def test_issue_card_raises_when_would_exceed_daily_cap():
    """Already spent £45, requesting £10 → exceeds £50 daily cap → raise."""
    from clawbot.skill_ctx import _LivePayments

    fake_ledger = MagicMock()
    fake_ledger.current_period_total_gbp = AsyncMock(return_value=Decimal("45.00"))
    fake_ledger.record = AsyncMock(return_value=1)

    payments = _LivePayments(secret_key="sk_live_real",
                              capital_ledger=fake_ledger,
                              live_mode_enabled=True,
                              capital_daily_cap_gbp=Decimal("50"),
                              capital_weekly_cap_gbp=Decimal("500"))

    with pytest.raises(RuntimeError, match="capital_cap_exceeded"):
        asyncio.run(payments.issue_card(
            cardholder_id="ich_x", daily_limit_usd=10, agent_id="cfo",
        ))


def test_issue_card_records_ledger_entry_on_success():
    """Successful issuance logs to the ledger BEFORE returning."""
    from clawbot.skill_ctx import _LivePayments

    fake_ledger = MagicMock()
    fake_ledger.current_period_total_gbp = AsyncMock(return_value=Decimal("0"))
    fake_ledger.record = AsyncMock(return_value=1)

    fake_card = MagicMock()
    fake_card.to_dict.return_value = {"id": "ic_live", "last4": "5678",
                                       "exp_month": 11, "exp_year": 2029, "status": "active",
                                       "cardholder": "ich_x"}

    payments = _LivePayments(secret_key="sk_live_real",
                              capital_ledger=fake_ledger,
                              live_mode_enabled=True,
                              capital_daily_cap_gbp=Decimal("100"),
                              capital_weekly_cap_gbp=Decimal("500"))

    with patch("clawbot.skill_ctx.stripe") as stripe_mod:
        stripe_mod.issuing.Card.create.return_value = fake_card
        result = asyncio.run(payments.issue_card(
            cardholder_id="ich_x", daily_limit_usd=10, agent_id="cfo",
        ))

    fake_ledger.record.assert_called_once()
    kwargs = fake_ledger.record.call_args.kwargs
    assert kwargs["action_type"] == "card_issued"
    assert kwargs["agent_id"] == "cfo"
    assert kwargs["is_live_mode"] is True
    assert result["id"] == "ic_live"
