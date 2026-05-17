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
