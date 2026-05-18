"""Swarm Z2.5 Task A — end-to-end attribution: a skill called with a
business-scoped ctx writes the business_id to the skill_calls table.

Postgres-gated (skips locally when asyncpg or the DB isn't reachable)."""
import pytest

asyncpg = pytest.importorskip("asyncpg")


@pytest.fixture
async def pool():
    try:
        pool = await asyncpg.create_pool(
            "postgresql://clawbot:clawbot@localhost:5432/clawbot",
            min_size=1, max_size=4,
        )
    except Exception:
        pytest.skip("local Postgres not available")
    yield pool
    await pool.close()


@pytest.mark.asyncio
async def test_skill_calls_records_business_id_from_ctx(pool):
    """Calling a skill through SkillRegistry.call(ctx) with ctx.business_id
    set MUST write business_id into the skill_calls row."""
    import tempfile
    from pathlib import Path
    from clawbot.skill_registry import SkillRegistry
    from clawbot.skill_ctx import make_noop_ctx

    SAMPLE = '''
META = {
    "name": "z25_attribution_probe",
    "description": "probe used to verify ctx.business_id reaches skill_calls",
    "params": {},
    "returns": {"ok": "bool"},
}

async def run(ctx) -> dict:
    return {"ok": True}
'''
    with tempfile.TemporaryDirectory() as tmp:
        skills_dir = Path(tmp)
        (skills_dir / "z25_attribution_probe.py").write_text(SAMPLE)
        reg = SkillRegistry(skills_dir=skills_dir)
        reg.discover()
        reg.set_stats_db(pool)

        # Clean prior probe rows so the test is deterministic
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM skill_calls WHERE skill_name='z25_attribution_probe'"
            )

        ctx = make_noop_ctx(
            caller_id="biz_runner", budget_usd=0.05,
            business_id="biz_attribution_test_xyz",
        )
        rec = await reg.call("z25_attribution_probe", {}, ctx)
        assert rec.ok

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT business_id, caller_id, ok FROM skill_calls "
                "WHERE skill_name='z25_attribution_probe' "
                "ORDER BY id DESC LIMIT 1"
            )
        assert row is not None, "no skill_calls row written"
        assert row["business_id"] == "biz_attribution_test_xyz"
        assert row["caller_id"] == "biz_runner"
        assert row["ok"] is True

        # Cleanup
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM skill_calls WHERE skill_name='z25_attribution_probe'"
            )


@pytest.mark.asyncio
async def test_skill_calls_business_id_null_for_executive_cycle(pool):
    """Executive cycles construct ctx without business_id. The row MUST have
    NULL — proves the additive migration didn't break the legacy path."""
    import tempfile
    from pathlib import Path
    from clawbot.skill_registry import SkillRegistry
    from clawbot.skill_ctx import make_noop_ctx

    SAMPLE = '''
META = {"name": "z25_exec_probe", "description": "p",
        "params": {}, "returns": {"ok": "bool"}}
async def run(ctx) -> dict:
    return {"ok": True}
'''
    with tempfile.TemporaryDirectory() as tmp:
        skills_dir = Path(tmp)
        (skills_dir / "z25_exec_probe.py").write_text(SAMPLE)
        reg = SkillRegistry(skills_dir=skills_dir)
        reg.discover()
        reg.set_stats_db(pool)
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM skill_calls WHERE skill_name='z25_exec_probe'")

        ctx = make_noop_ctx(caller_id="ceo", budget_usd=0.10)  # no business_id
        await reg.call("z25_exec_probe", {}, ctx)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT business_id FROM skill_calls "
                "WHERE skill_name='z25_exec_probe' ORDER BY id DESC LIMIT 1"
            )
        assert row is not None
        assert row["business_id"] is None
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM skill_calls WHERE skill_name='z25_exec_probe'")
