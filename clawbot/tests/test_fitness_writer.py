import json
import time
import pytest

from clawbot.fitness_writer import (
    append_observation, read_recent_observations, trim_observations,
    compute_and_save_fitness, refresh_all_fitness, list_active_agents,
    FITNESS_WINDOW_S,
)


def test_append_observation_creates_jsonl(tmp_path):
    append_observation(tmp_path, "ceo", duration_s=1.5, success=True, kind="executive_cycle")
    path = tmp_path / "ceo" / "observations.jsonl"
    assert path.exists()
    line = path.read_text().strip()
    data = json.loads(line)
    assert data["duration_s"] == 1.5
    assert data["success"] is True


def test_read_recent_returns_entries_inside_window(tmp_path):
    append_observation(tmp_path, "ceo", 0.1, True)
    append_observation(tmp_path, "ceo", 0.2, False)
    obs = read_recent_observations(tmp_path, "ceo")
    assert len(obs) == 2


def test_read_recent_filters_out_stale_entries(tmp_path):
    """Entries older than the window are excluded."""
    path = tmp_path / "ceo"
    path.mkdir()
    old_ts = time.time() - (FITNESS_WINDOW_S + 100)
    new_ts = time.time()
    (path / "observations.jsonl").write_text(
        json.dumps({"ts": old_ts, "duration_s": 1, "success": True, "kind": "x"}) + "\n" +
        json.dumps({"ts": new_ts, "duration_s": 2, "success": True, "kind": "x"}) + "\n",
        encoding="utf-8",
    )
    obs = read_recent_observations(tmp_path, "ceo")
    assert len(obs) == 1
    assert obs[0].duration_s == 2


def test_read_recent_skips_malformed_lines(tmp_path):
    path = tmp_path / "ceo"
    path.mkdir()
    (path / "observations.jsonl").write_text(
        "garbage line\n" +
        json.dumps({"ts": time.time(), "duration_s": 1, "success": True}) + "\n" +
        "{\"missing_ts\": true}\n",
        encoding="utf-8",
    )
    obs = read_recent_observations(tmp_path, "ceo")
    assert len(obs) == 1


def test_trim_observations_removes_stale_entries(tmp_path):
    path = tmp_path / "ceo"
    path.mkdir()
    old_ts = time.time() - (FITNESS_WINDOW_S + 100)
    new_ts = time.time()
    (path / "observations.jsonl").write_text(
        json.dumps({"ts": old_ts, "duration_s": 1, "success": True}) + "\n" +
        json.dumps({"ts": new_ts, "duration_s": 2, "success": True}) + "\n",
        encoding="utf-8",
    )
    kept = trim_observations(tmp_path, "ceo")
    assert kept == 1


def test_compute_and_save_fitness_writes_file(tmp_path):
    append_observation(tmp_path, "ceo", 0.5, True)
    append_observation(tmp_path, "ceo", 1.0, True)
    append_observation(tmp_path, "ceo", 2.0, False)
    score = compute_and_save_fitness(tmp_path, "ceo", revenue_share_gbp=10.0)
    assert score is not None
    assert score.tasks_completed == 2
    assert score.tasks_failed == 1
    fitness_path = tmp_path / "ceo" / "fitness.json"
    assert fitness_path.exists()


def test_compute_and_save_returns_none_when_no_observations(tmp_path):
    score = compute_and_save_fitness(tmp_path, "ghost", revenue_share_gbp=0.0)
    assert score is None


async def test_refresh_all_splits_revenue_equally(tmp_path):
    append_observation(tmp_path, "ceo", 1.0, True)
    append_observation(tmp_path, "cfo", 1.0, True)
    append_observation(tmp_path, "cmo", 1.0, True)
    results = await refresh_all_fitness(tmp_path, total_revenue_7d_gbp=30.0)
    assert set(results.keys()) == {"ceo", "cfo", "cmo"}
    for score in results.values():
        assert score is not None
        assert score.revenue_7d_gbp == pytest.approx(10.0)


async def test_refresh_all_skips_agents_with_no_observations(tmp_path):
    (tmp_path / "ghost").mkdir()  # directory exists but no observations.jsonl
    append_observation(tmp_path, "ceo", 1.0, True)
    results = await refresh_all_fitness(tmp_path, 5.0)
    assert "ceo" in results
    assert "ghost" not in results


def test_list_active_agents_returns_agents_with_observations(tmp_path):
    append_observation(tmp_path, "ceo", 1.0, True)
    (tmp_path / "no_obs_yet").mkdir()
    agents = list_active_agents(tmp_path)
    assert "ceo" in agents
    assert "no_obs_yet" not in agents


async def test_refresh_all_handles_zero_active_agents(tmp_path):
    results = await refresh_all_fitness(tmp_path, 100.0)
    assert results == {}


async def test_refresh_all_fitness_uses_attributed_revenue_when_causal_store_provided(tmp_path):
    from unittest.mock import MagicMock

    for agent_id, duration, success in [("ceo", 5.0, True), ("cfo", 3.0, True)]:
        append_observation(tmp_path, agent_id, duration, success)

    causal_store = MagicMock()

    async def fake_attributed(agent_id):
        return 8.0 if agent_id == "ceo" else 2.0

    async def fake_rate(agent_id):
        return 0.8 if agent_id == "ceo" else 0.4

    causal_store.attributed_revenue_7d = fake_attributed
    causal_store.attribution_rate = fake_rate

    results = await refresh_all_fitness(tmp_path, total_revenue_7d_gbp=10.0,
                                        causal_store=causal_store)

    assert results["ceo"] is not None
    assert results["cfo"] is not None
    assert results["ceo"].attributed_revenue_7d_gbp == pytest.approx(8.0)
    assert results["cfo"].attributed_revenue_7d_gbp == pytest.approx(2.0)


async def test_refresh_all_fitness_falls_back_to_equal_share_without_causal_store(tmp_path):
    for agent_id in ("ceo", "cfo"):
        append_observation(tmp_path, agent_id, 5.0, True)

    results = await refresh_all_fitness(tmp_path, total_revenue_7d_gbp=10.0)

    assert results["ceo"] is not None
    assert results["cfo"] is not None
    assert results["ceo"].attributed_revenue_7d_gbp == pytest.approx(0.0)
    assert results["cfo"].attributed_revenue_7d_gbp == pytest.approx(0.0)
