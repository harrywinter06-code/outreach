import json

from clawbot.lineage import LineageStore, soul_sha


def test_soul_sha_is_deterministic():
    a = soul_sha("hello world")
    b = soul_sha("hello world")
    assert a == b
    assert a != soul_sha("hello world!")


def test_current_generation_zero_when_no_history(tmp_path):
    store = LineageStore(tmp_path)
    assert store.current_generation("ceo") == 0


def test_append_creates_generation_one_then_two(tmp_path):
    store = LineageStore(tmp_path)
    r1 = store.append("ceo", "parent text", "child text v1", fitness_before=0.10, mutation_excerpt="new focus")
    r2 = store.append("ceo", "child text v1", "child text v2", fitness_before=0.15, mutation_excerpt="refined")

    assert r1.generation == 1
    assert r2.generation == 2
    assert r2.parent_sha == soul_sha("child text v1")


def test_append_writes_file_in_agent_dir(tmp_path):
    store = LineageStore(tmp_path)
    store.append("cmo", "p", "c", 0.5, "x")
    file_path = tmp_path / "lineage" / "cmo" / "generation_001.json"
    assert file_path.exists()
    data = json.loads(file_path.read_text())
    assert data["agent_id"] == "cmo"
    assert data["fitness_before"] == 0.5


def test_history_returns_chronological(tmp_path):
    store = LineageStore(tmp_path)
    store.append("ceo", "a", "b", 0.1, "first")
    store.append("ceo", "b", "c", 0.2, "second")
    store.append("ceo", "c", "d", 0.3, "third")

    hist = store.history("ceo")
    assert len(hist) == 3
    assert [r.generation for r in hist] == [1, 2, 3]
    assert [r.fitness_before for r in hist] == [0.1, 0.2, 0.3]


def test_history_empty_for_unknown_agent(tmp_path):
    store = LineageStore(tmp_path)
    assert store.history("nobody") == []


def test_fitness_trend_detects_uptrend(tmp_path):
    store = LineageStore(tmp_path)
    for f in [0.10, 0.15, 0.30]:
        store.append("ceo", "parent", "child", f, "x")
    assert store.fitness_trend("ceo") == "up"


def test_fitness_trend_detects_downtrend(tmp_path):
    store = LineageStore(tmp_path)
    for f in [0.50, 0.30, 0.10]:
        store.append("ceo", "parent", "child", f, "x")
    assert store.fitness_trend("ceo") == "down"


def test_fitness_trend_flat_within_5pct_band(tmp_path):
    store = LineageStore(tmp_path)
    for f in [0.30, 0.305, 0.31]:
        store.append("ceo", "parent", "child", f, "x")
    assert store.fitness_trend("ceo") == "flat"


def test_fitness_trend_insufficient_data(tmp_path):
    store = LineageStore(tmp_path)
    store.append("ceo", "p", "c", 0.5, "x")
    assert store.fitness_trend("ceo") == "insufficient_data"


def test_mutation_excerpt_truncated_to_240(tmp_path):
    store = LineageStore(tmp_path)
    long_excerpt = "x" * 500
    r = store.append("ceo", "p", "c", 0.1, long_excerpt)
    assert len(r.mutation_excerpt) == 240
