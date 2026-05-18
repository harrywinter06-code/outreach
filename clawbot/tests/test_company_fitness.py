"""company_fitness: single score for the whole organism."""
from decimal import Decimal

from clawbot.company_fitness import compute_company_fitness, CompanyFitnessScore


def test_zero_revenue_caps_score_at_0_30():
    score = compute_company_fitness(
        revenue_7d_gbp=Decimal("0"),
        plans_active=2, plans_advanced_7d=4, plans_pivoted_7d=1,
        capital_deployed_7d_gbp=Decimal("10"),
        skill_calls_7d=50, skill_calls_success_7d=45,
    )
    assert score.score <= 0.30


def test_high_revenue_high_signal_scores_high():
    score = compute_company_fitness(
        revenue_7d_gbp=Decimal("500"),
        plans_active=3, plans_advanced_7d=10, plans_pivoted_7d=2,
        capital_deployed_7d_gbp=Decimal("50"),
        skill_calls_7d=200, skill_calls_success_7d=190,
    )
    assert score.score > 0.70
    assert score.revenue_score > 0.9
    assert score.plan_velocity > 0.7
    assert score.skill_call_success_rate > 0.9


def test_no_skill_calls_yields_zero_success_rate_not_div_by_zero():
    score = compute_company_fitness(
        revenue_7d_gbp=Decimal("0"),
        plans_active=0, plans_advanced_7d=0, plans_pivoted_7d=0,
        capital_deployed_7d_gbp=Decimal("0"),
        skill_calls_7d=0, skill_calls_success_7d=0,
    )
    assert score.skill_call_success_rate == 0.0
    assert score.score == 0.0


def test_breakdown_contains_all_components():
    score = compute_company_fitness(
        revenue_7d_gbp=Decimal("10"),
        plans_active=1, plans_advanced_7d=2, plans_pivoted_7d=1,
        capital_deployed_7d_gbp=Decimal("5"),
        skill_calls_7d=10, skill_calls_success_7d=8,
    )
    assert "revenue_score" in score.breakdown
    assert "plan_velocity" in score.breakdown
    assert "skill_call_success_rate" in score.breakdown
    assert "capital_efficiency" in score.breakdown
