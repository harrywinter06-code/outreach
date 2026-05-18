"""End-to-end integration: _LivePayments + CapitalLedger + cap enforcement."""
import asyncio
import pytest
from decimal import Decimal

asyncpg = pytest.importorskip("asyncpg")


@pytest.fixture
async def pool():
    try:
        pool = await asyncpg.create_pool(
            "postgresql://clawbot:clawbot@localhost:5432/clawbot",
            min_size=1, max_size=2,
        )
    except Exception:
        pytest.skip("local Postgres not available")
    yield pool
    await pool.close()


@pytest.mark.asyncio
async def test_issue_card_writes_ledger_row_and_cap_query_reflects_it(pool):
    """Full path: issue card → ledger row → cap query sees it."""
    from clawbot.capital_ledger import CapitalLedger
    from clawbot.skill_ctx import _LivePayments
    from unittest.mock import MagicMock, patch

    ledger = CapitalLedger(pool)
    await ledger.init_schema()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM capital_ledger WHERE agent_id='test_integ_cfo'")

    fake_card = MagicMock()
    fake_card.to_dict.return_value = {
        "id": "ic_integ_test_xyz", "last4": "9999",
        "exp_month": 6, "exp_year": 2029, "status": "active",
        "cardholder": "ich_x",
    }

    payments = _LivePayments(
        secret_key="sk_test_integ",
        capital_ledger=ledger,
        live_mode_enabled=False,
        capital_daily_cap_gbp=Decimal("100"),
        capital_weekly_cap_gbp=Decimal("500"),
    )

    with patch("clawbot.skill_ctx.stripe") as stripe_mod:
        stripe_mod.issuing.Card.create.return_value = fake_card
        result = await payments.issue_card(
            cardholder_id="ich_x", daily_limit_usd=10, agent_id="test_integ_cfo",
        )

    # Ledger row written
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT amount_gbp, is_live_mode FROM capital_ledger "
            "WHERE stripe_object_id=$1",
            result["id"],
        )
    assert row is not None
    assert float(row["amount_gbp"]) == 10.0
    # Test mode key → is_live_mode should be False
    assert row["is_live_mode"] is False

    # Cap query sees the entry under live_only=False
    total_all = await ledger.current_period_total_gbp(period_hours=24, live_only=False)
    assert total_all >= Decimal("10.0")
    # Test-mode entry NOT counted under live_only=True
    total_live = await ledger.current_period_total_gbp(period_hours=24, live_only=True)
    assert total_live == Decimal("0")


@pytest.mark.asyncio
async def test_hypothesis_kill_cascades_to_linked_plans(pool):
    """Killing a hypothesis must cascade plans linked via hypothesis_id."""
    from clawbot.hypothesis_store import HypothesisStore
    from clawbot.plan_store import PlanStore

    hyp = HypothesisStore(pool)
    plan = PlanStore(pool)
    # init_schema is no-op on HypothesisStore now; db schema is single source of truth
    await plan.init_schema()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM active_hypothesis WHERE name LIKE 'test_integ_%'")
        await conn.execute("DELETE FROM plans WHERE agent_id='test_integ_cmo'")

    hid = await hyp.add_hypothesis(
        name="test_integ_h1", description="x",
        kill_criteria={"max_days_without_revenue": 14}, weight=0.5,
    )
    await plan.create_plan(
        agent_id="test_integ_cmo", hypothesis="m",
        milestones=[
            {"hypothesis": "m1", "success_criteria": ["c1"]},
            {"hypothesis": "m2", "success_criteria": ["c2"]},
        ],
        hypothesis_id=hid,
    )
    # Both milestones linked
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT status, hypothesis_id FROM plans "
            "WHERE agent_id='test_integ_cmo' ORDER BY milestone_idx",
        )
    assert len(rows) == 2
    assert all(r["hypothesis_id"] == hid for r in rows)
    assert rows[0]["status"] == "active"
    assert rows[1]["status"] == "pending"

    # Kill the hypothesis
    await hyp.kill_hypothesis_by_id(hypothesis_id=hid, reason="test")

    # All linked plans cascaded to abandoned
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT status FROM plans WHERE agent_id='test_integ_cmo'"
        )
    assert all(r["status"] == "abandoned" for r in rows)
