"""Tests for the plans table CRUD.

These tests use an asyncpg pool fixture that points at a test database; if
asyncpg is unavailable locally (as documented in operating_facts.md), the
tests skip rather than fail. The real coverage lives in CI on the VPS."""
import json
import pytest
import asyncio


asyncpg = pytest.importorskip("asyncpg")


@pytest.fixture
async def pool(monkeypatch):
    """Real asyncpg pool; skipped if Postgres isn't reachable."""
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
async def test_init_schema_creates_plans_table(pool):
    from clawbot.plan_store import PlanStore
    store = PlanStore(pool)
    await store.init_schema()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='plans' ORDER BY column_name"
        )
    cols = {r["column_name"] for r in rows}
    assert {"plan_id", "agent_id", "milestone_idx", "hypothesis",
            "success_criteria", "evidence", "status"} <= cols


@pytest.mark.asyncio
async def test_create_plan_and_get_current_milestone(pool):
    from clawbot.plan_store import PlanStore
    store = PlanStore(pool)
    await store.init_schema()
    await store.create_plan(
        agent_id="cmo",
        hypothesis="Substack as primary distribution channel",
        milestones=[
            {"hypothesis": "Publish 3 posts in 7 days", "success_criteria": ["3 posts published"]},
            {"hypothesis": "Gain 50 free subscribers", "success_criteria": ["subs >= 50"]},
        ],
    )
    current = await store.get_current_milestone(agent_id="cmo")
    assert current is not None
    assert current.milestone_idx == 0
    assert "Publish 3 posts" in current.hypothesis


@pytest.mark.asyncio
async def test_advance_promotes_next_milestone(pool):
    from clawbot.plan_store import PlanStore
    store = PlanStore(pool)
    await store.init_schema()
    await store.create_plan(
        agent_id="cmo_advance",
        hypothesis="x",
        milestones=[
            {"hypothesis": "m1", "success_criteria": ["c1"]},
            {"hypothesis": "m2", "success_criteria": ["c2"]},
        ],
    )
    await store.advance_milestone(agent_id="cmo_advance")
    current = await store.get_current_milestone(agent_id="cmo_advance")
    assert current is not None
    assert current.milestone_idx == 1
    assert current.hypothesis == "m2"


@pytest.mark.asyncio
async def test_advance_past_last_returns_none(pool):
    from clawbot.plan_store import PlanStore
    store = PlanStore(pool)
    await store.init_schema()
    await store.create_plan(
        agent_id="cmo_last",
        hypothesis="x",
        milestones=[{"hypothesis": "only", "success_criteria": ["c"]}],
    )
    await store.advance_milestone(agent_id="cmo_last")
    current = await store.get_current_milestone(agent_id="cmo_last")
    assert current is None  # all milestones done


@pytest.mark.asyncio
async def test_add_evidence_appends_to_json_list(pool):
    from clawbot.plan_store import PlanStore
    store = PlanStore(pool)
    await store.init_schema()
    await store.create_plan(
        agent_id="cto_evidence", hypothesis="x",
        milestones=[{"hypothesis": "m", "success_criteria": ["c"]}],
    )
    await store.add_evidence(agent_id="cto_evidence", item={"kind": "skill_call", "skill": "fs_write", "result": "ok"})
    await store.add_evidence(agent_id="cto_evidence", item={"kind": "observation", "text": "page returned 200"})
    current = await store.get_current_milestone(agent_id="cto_evidence")
    assert current is not None
    items = json.loads(current.evidence)
    assert len(items) == 2
    assert items[0]["skill"] == "fs_write"


@pytest.mark.asyncio
async def test_pivot_marks_current_pivoted_and_creates_new_plan(pool):
    from clawbot.plan_store import PlanStore
    store = PlanStore(pool)
    await store.init_schema()
    await store.create_plan(
        agent_id="cmo_pivot", hypothesis="old",
        milestones=[{"hypothesis": "m1", "success_criteria": ["c"]}],
    )
    await store.pivot(
        agent_id="cmo_pivot",
        reason="No engagement after 7 days",
        new_hypothesis="LinkedIn as primary",
        new_milestones=[{"hypothesis": "post 5 LinkedIn pieces", "success_criteria": ["5 posts"]}],
    )
    current = await store.get_current_milestone(agent_id="cmo_pivot")
    assert current is not None
    assert "LinkedIn" in current.hypothesis
