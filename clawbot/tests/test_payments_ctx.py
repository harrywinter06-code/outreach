import asyncio
from unittest.mock import MagicMock, patch
import pytest


def test_noop_payments_returns_stub_ids():
    from clawbot.skill_ctx import make_noop_ctx
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    result = asyncio.run(ctx.payments.create_product(name="x", description="y"))
    assert result["id"].startswith("prod_noop")


def test_live_payments_create_product_calls_stripe():
    with patch("clawbot.skill_ctx.stripe") as mock_stripe:
        mock_stripe.Product.create = MagicMock(return_value=MagicMock(
            id="prod_xyz", to_dict=lambda: {"id": "prod_xyz", "name": "x"}
        ))
        from clawbot.skill_ctx import _LivePayments
        p = _LivePayments(secret_key="sk_test_x")
        result = asyncio.run(p.create_product(name="x", description="y"))
        assert result["id"] == "prod_xyz"
        mock_stripe.Product.create.assert_called_once()


def test_live_payments_rejects_missing_key():
    from clawbot.skill_ctx import _LivePayments
    with pytest.raises(ValueError, match="STRIPE_SECRET_KEY"):
        _LivePayments(secret_key="")
