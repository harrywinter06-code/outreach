import pytest
from clawbot.fitness import (
    compute_fitness, FitnessScore, bottom_percentile,
    load_fitness_from_metrics, save_fitness,
)


def test_zero_revenue_caps_fitness_at_0_30():
    score = compute_fitness(
        agent_id="cfo",
        revenue_7d_gbp=0.0,
        tasks_completed=100,
        tasks_failed=0,
        avg_latency_s=1.0,
    )
    assert score.score <= 0.30


def test_high_revenue_dominates_score():
    with_revenue = compute_fitness(
        agent_id="cfo",
        revenue_7d_gbp=50.0,
        tasks_completed=10,
        tasks_failed=10,
        avg_latency_s=60.0,
    )
    no_revenue = compute_fitness(
        agent_id="cfo",
        revenue_7d_gbp=0.0,
        tasks_completed=100,
        tasks_failed=0,
        avg_latency_s=1.0,
    )
    assert with_revenue.score > no_revenue.score


def test_score_is_between_0_and_1():
    for revenue in [0.0, 1.0, 10.0, 100.0, 1000.0]:
        score = compute_fitness(
            agent_id="test",
            revenue_7d_gbp=revenue,
            tasks_completed=50,
            tasks_failed=5,
            avg_latency_s=30.0,
        )
        assert 0.0 <= score.score <= 1.0


def test_all_failed_tasks_contributes_zero_completion():
    score = compute_fitness(
        agent_id="test",
        revenue_7d_gbp=0.0,
        tasks_completed=0,
        tasks_failed=10,
        avg_latency_s=30.0,
    )
    assert score.score <= 0.30  # no revenue cap applies


def test_no_tasks_does_not_raise():
    score = compute_fitness(
        agent_id="test",
        revenue_7d_gbp=0.0,
        tasks_completed=0,
        tasks_failed=0,
        avg_latency_s=30.0,
    )
    assert 0.0 <= score.score <= 0.30  # no revenue means capped at 0.30


def test_bottom_percentile_returns_lowest_scores():
    scores = [
        FitnessScore("a", 0, 0, 0, 0, 0.90),
        FitnessScore("b", 0, 0, 0, 0, 0.10),
        FitnessScore("c", 0, 0, 0, 0, 0.50),
        FitnessScore("d", 0, 0, 0, 0, 0.20),
        FitnessScore("e", 0, 0, 0, 0, 0.80),
    ]
    bottom = bottom_percentile(scores, pct=0.20)
    assert len(bottom) == 1
    assert bottom[0].agent_id == "b"


def test_bottom_percentile_minimum_one():
    scores = [FitnessScore("only", 0, 0, 0, 0, 0.50)]
    bottom = bottom_percentile(scores, pct=0.20)
    assert len(bottom) == 1


def test_save_and_load_fitness_roundtrip(tmp_path):
    score = compute_fitness(
        agent_id="ceo",
        revenue_7d_gbp=12.50,
        tasks_completed=80,
        tasks_failed=5,
        avg_latency_s=45.0,
    )
    save_fitness(tmp_path, score)

    loaded = load_fitness_from_metrics(tmp_path, "ceo")
    assert loaded is not None
    assert loaded.agent_id == "ceo"
    assert loaded.revenue_7d_gbp == pytest.approx(12.50)
    assert loaded.score == pytest.approx(score.score)


def test_load_fitness_returns_none_when_missing(tmp_path):
    result = load_fitness_from_metrics(tmp_path, "nonexistent-agent")
    assert result is None


def test_do_nothing_agent_scores_below_effort_agent():
    """Effort with failure must outrank zero-work zero-revenue equilibrium."""
    do_nothing = compute_fitness(
        agent_id="lazy",
        revenue_7d_gbp=0.0,
        tasks_completed=0,
        tasks_failed=0,
        avg_latency_s=0.0,
    )
    tried_and_failed = compute_fitness(
        agent_id="tried",
        revenue_7d_gbp=0.0,
        tasks_completed=5,
        tasks_failed=5,
        avg_latency_s=60.0,
    )
    assert do_nothing.score < tried_and_failed.score
    assert do_nothing.score == 0.0  # explicit no-op tax


def test_do_nothing_with_revenue_is_not_penalized():
    """Revenue overrides the no-op tax — affiliate income with no internal tasks is valid."""
    score = compute_fitness(
        agent_id="affiliate",
        revenue_7d_gbp=10.0,
        tasks_completed=0,
        tasks_failed=0,
        avg_latency_s=0.0,
    )
    assert score.score > 0.0


def test_fitness_score_has_attribution_fields():
    score = compute_fitness(
        agent_id="ceo",
        revenue_7d_gbp=10.0,
        tasks_completed=5,
        tasks_failed=1,
        avg_latency_s=30.0,
        attributed_revenue_7d_gbp=8.0,
        attribution_rate=0.5,
    )
    assert score.attributed_revenue_7d_gbp == pytest.approx(8.0)
    assert score.attribution_rate == pytest.approx(0.5)


def test_attributed_revenue_does_not_change_score_formula():
    base = compute_fitness("ceo", 10.0, 5, 1, 30.0)
    with_attr = compute_fitness("ceo", 10.0, 5, 1, 30.0,
                                attributed_revenue_7d_gbp=10.0, attribution_rate=1.0)
    assert base.score == pytest.approx(with_attr.score)


def test_save_and_load_fitness_preserves_attribution_fields(tmp_path):
    score = compute_fitness(
        agent_id="cfo",
        revenue_7d_gbp=5.0,
        tasks_completed=10,
        tasks_failed=0,
        avg_latency_s=20.0,
        attributed_revenue_7d_gbp=3.5,
        attribution_rate=0.75,
    )
    save_fitness(tmp_path, score)
    loaded = load_fitness_from_metrics(tmp_path, "cfo")
    assert loaded is not None
    assert loaded.attributed_revenue_7d_gbp == pytest.approx(3.5)
    assert loaded.attribution_rate == pytest.approx(0.75)


def test_load_fitness_handles_missing_attribution_fields(tmp_path):
    """Old fitness.json files without attribution fields must load cleanly."""
    import json
    agent_dir = tmp_path / "old-agent"
    agent_dir.mkdir()
    (agent_dir / "fitness.json").write_text(json.dumps({
        "agent_id": "old-agent",
        "revenue_7d_gbp": 5.0,
        "tasks_completed": 3,
        "tasks_failed": 1,
        "avg_latency_s": 20.0,
        "score": 0.25,
    }), encoding="utf-8")
    loaded = load_fitness_from_metrics(tmp_path, "old-agent")
    assert loaded is not None
    assert loaded.attributed_revenue_7d_gbp == pytest.approx(0.0)
    assert loaded.attribution_rate == pytest.approx(0.0)
