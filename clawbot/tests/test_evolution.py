import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from clawbot.evolution import (
    run_evolution_cycle,
    _is_mutable_target,
    _extract_immutable,
    _validate_mutation,
    MutationRejected,
    MUTATION_PROMPT,
    FORBIDDEN_MUTATION_TARGETS,
)
from clawbot.fitness import FitnessScore


_SAMPLE_SOUL = """## IMMUTABLE

**Identity:** Test agent.
**Hard rules:** Revenue first.

## MUTABLE

### current_focus
Awaiting first task.

### active_tasks
None.
"""


def _write_soul(agents_dir: Path, agent_id: str, content: str = _SAMPLE_SOUL) -> Path:
    soul = agents_dir / agent_id / "SOUL.md"
    soul.parent.mkdir(parents=True, exist_ok=True)
    soul.write_text(content, encoding="utf-8")
    return soul


def _score(agent_id: str, fitness: float = 0.10) -> FitnessScore:
    return FitnessScore(
        agent_id=agent_id,
        revenue_7d_gbp=0.0,
        tasks_completed=0,
        tasks_failed=0,
        avg_latency_s=0.0,
        score=fitness,
    )


def test_meta_is_forbidden_target():
    assert _is_mutable_target("meta") is False


def test_all_shareholders_are_forbidden():
    for sid in [
        "shareholder-activist", "shareholder-conservative",
        "shareholder-diversifier", "shareholder-longterm", "shareholder-opportunist",
    ]:
        assert _is_mutable_target(sid) is False, f"{sid} must be constitutional"


def test_executive_ids_are_mutable():
    for executive in ["ceo", "cfo", "cmo", "cto", "coo"]:
        assert _is_mutable_target(executive) is True


def test_dynamic_worker_is_mutable():
    assert _is_mutable_target("content-writer-001") is True


def test_extract_immutable_returns_pre_mutable_text():
    immutable = _extract_immutable(_SAMPLE_SOUL)
    assert "Identity" in immutable
    assert "current_focus" not in immutable


def test_extract_immutable_returns_whole_text_when_no_mutable_marker():
    text = "## ANYTHING\nnothing mutable here"
    assert _extract_immutable(text) == text


def test_validate_mutation_accepts_clean_output():
    raw = "## MUTABLE\n\n### current_focus\nNew focus."
    validated = _validate_mutation(raw)
    assert validated.startswith("## MUTABLE")


def test_validate_mutation_rejects_immutable_string():
    raw = "## MUTABLE\n\n## IMMUTABLE\nattempting to redefine."
    with pytest.raises(MutationRejected, match="IMMUTABLE"):
        _validate_mutation(raw)


def test_validate_mutation_rejects_duplicate_mutable_header():
    raw = "## MUTABLE\nfoo\n## MUTABLE\nbar"
    with pytest.raises(MutationRejected, match="MUTABLE"):
        _validate_mutation(raw)


def test_validate_mutation_rejects_empty_output():
    with pytest.raises(MutationRejected, match="empty"):
        _validate_mutation("   ")


def test_validate_mutation_rejects_preamble_before_header():
    raw = "Here is the new section:\n## MUTABLE\nfoo"
    with pytest.raises(MutationRejected, match="start"):
        _validate_mutation(raw)


@pytest.mark.asyncio
async def test_evolution_skips_meta_even_when_in_bottom_percentile(tmp_path):
    _write_soul(tmp_path, "meta")
    _write_soul(tmp_path, "ceo")
    scores = [_score("meta", 0.05), _score("ceo", 0.50)]

    pool = MagicMock()
    pool.complete = AsyncMock(return_value="## MUTABLE\nrewritten")

    mutated = await run_evolution_cycle(tmp_path, scores, pool)
    assert "meta" not in mutated
    pool.complete.assert_not_called()  # ceo is not in the bottom 20% (only 1 of 2 included)


@pytest.mark.asyncio
async def test_evolution_skips_shareholder_when_low_fitness(tmp_path):
    _write_soul(tmp_path, "shareholder-activist")
    _write_soul(tmp_path, "ceo")
    scores = [_score("shareholder-activist", 0.05), _score("ceo", 0.50)]
    pool = MagicMock()
    pool.complete = AsyncMock(return_value="## MUTABLE\nrewritten")

    mutated = await run_evolution_cycle(tmp_path, scores, pool)
    assert "shareholder-activist" not in mutated


@pytest.mark.asyncio
async def test_evolution_mutates_low_scoring_ceo(tmp_path):
    _write_soul(tmp_path, "ceo")
    scores = [_score("ceo", 0.05)]
    pool = MagicMock()
    pool.complete = AsyncMock(return_value="## MUTABLE\n\n### current_focus\nPivot to research reports.\n")

    mutated = await run_evolution_cycle(tmp_path, scores, pool)
    assert "ceo" in mutated
    new_content = (tmp_path / "ceo" / "SOUL.md").read_text()
    assert "Pivot to research reports" in new_content
    assert "## IMMUTABLE" in new_content  # preserved


@pytest.mark.asyncio
async def test_evolution_rejects_mutation_that_writes_immutable(tmp_path):
    _write_soul(tmp_path, "ceo")
    scores = [_score("ceo", 0.05)]
    pool = MagicMock()
    pool.complete = AsyncMock(return_value="## MUTABLE\n## IMMUTABLE\nrewriting constraints")

    mutated = await run_evolution_cycle(tmp_path, scores, pool)
    assert mutated == []
    # SOUL.md unchanged
    assert (tmp_path / "ceo" / "SOUL.md").read_text() == _SAMPLE_SOUL


@pytest.mark.asyncio
async def test_evolution_prompt_includes_immutable_section(tmp_path):
    _write_soul(tmp_path, "ceo")
    scores = [_score("ceo", 0.05)]
    pool = MagicMock()
    pool.complete = AsyncMock(return_value="## MUTABLE\nrewritten")

    await run_evolution_cycle(tmp_path, scores, pool)
    prompt_arg = pool.complete.call_args.args[0][1]["content"]
    assert "Identity:** Test agent" in prompt_arg
    assert "Revenue first" in prompt_arg
    assert "BIND YOUR REWRITE" in prompt_arg


def test_forbidden_targets_match_constitutional_agents():
    """Sanity check on the allowlist contents."""
    assert "meta" in FORBIDDEN_MUTATION_TARGETS
    assert all(
        sid in FORBIDDEN_MUTATION_TARGETS
        for sid in [
            "shareholder-activist", "shareholder-conservative",
            "shareholder-diversifier", "shareholder-longterm", "shareholder-opportunist",
        ]
    )
    # CEO etc must NOT be forbidden — they evolve.
    for executive in ["ceo", "cfo", "cmo", "cto", "coo"]:
        assert executive not in FORBIDDEN_MUTATION_TARGETS


def test_mutation_prompt_template_has_required_placeholders():
    for placeholder in ["{immutable_section}", "{mutable_section}", "{revenue", "{score"]:
        assert placeholder in MUTATION_PROMPT
