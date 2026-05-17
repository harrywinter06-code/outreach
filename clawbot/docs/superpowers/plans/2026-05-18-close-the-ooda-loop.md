# Close the OODA Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop clawbot's executives from looping in pure deliberation. Give them awareness of the 37 skills they already have access to, persistent multi-cycle plans they execute against, and an explicit company-wide hypothesis state the board can pivot when it isn't working. After this lands, the substrate is generic — the agents can in principle run any business their planning produces.

**Architecture:** Three layers, each independently testable, each landing in production behind a feature flag that defaults to *on*. Layer 1 (skill affordance) renders the SkillRegistry catalog into the executive prompt at build time, filtered per role; this alone turns the existing 0 skill calls/day into something positive. Layer 2 (plans) adds a `plans` SQL table holding each executive's committed milestone chain; the cycle prompt is restructured from "what's your next action?" to "your current milestone is X; here's evidence so far; advance, gather, or pivot." Layer 3 (hypothesis) introduces a single `active_hypothesis` row the board reads and overwrites on PIVOT outcomes — wiring into the existing `BoardVotingSystem` rather than duplicating it.

**Tech Stack:** Python 3.12+, `asyncpg` (existing), `pydantic` types via dataclasses (existing pattern), pytest. No new pip dependencies. The new tables are added to the existing migration path in `db.py`.

**What this is NOT:** It is not a niche pick. It is not a product strategy. It is not a marketing rewrite. It deliberately leaves the strategic question open and instead makes the substrate capable of executing whatever strategy the agents commit to.

**Pre-mortem:** The most likely failure mode is that after Layer 1 ships, the executives start calling skills randomly — `fs_write` to scratchpad files no one reads, `http_fetch` against random URLs, `account_create` for services they don't need. Layer 2 (plans) is what disciplines this: skills must serve a current-milestone evidence collection, not free-form curiosity. The second most likely failure mode is that the migration writes break existing fitness/evolution callers that assume the old brain schema; mitigated by additive migrations only — no column drops, no renames.

---

## File Structure

**Create:**
- `src/clawbot/skill_catalog_renderer.py` — pure-function module that renders a role-filtered skill catalog into a prompt block
- `src/clawbot/plan_store.py` — async CRUD over the new `plans` table
- `src/clawbot/hypothesis_store.py` — async CRUD over the new `active_hypothesis` table
- `tests/test_skill_catalog_renderer.py`
- `tests/test_plan_store.py`
- `tests/test_hypothesis_store.py`
- `tests/test_scheduler_plan_integration.py`
- `tests/test_board_hypothesis_pivot.py`

**Modify:**
- `src/clawbot/db.py` — add `plans` and `active_hypothesis` tables to the schema-init function
- `src/clawbot/scheduler.py` — both `_run_executive_cycle` and `_run_lieutenant_cycle` rebuild their prompts via the new renderer and plan-store; cycle response parsed for plan-update actions
- `src/clawbot/board.py` — when an outcome is `PIVOT` or `RESET`, write a new `active_hypothesis` row generated from the resolution's `action_required` text via a one-shot LLM call
- `src/clawbot/directive_router.py` — add three plan-update action handlers (`plan_init`, `plan_advance`, `plan_pivot`) routed through `_get_handler`

**Out of scope (defer to follow-up):**
- A `validate_demand` builtin skill (Fix 3 from the audit) — useful but not load-bearing for the loop closure
- A long-running distribution channel commitment (Fix 4) — once the loop is closed, this becomes a milestone the CMO commits to autonomously

---

## Task 1: Skill catalog renderer (pure function)

**Files:**
- Create: `src/clawbot/skill_catalog_renderer.py`
- Create: `tests/test_skill_catalog_renderer.py`

Per-role filtering avoids overloading any single executive with all 37 skills (each takes prompt tokens and the LLM's attention dilutes). The mapping is small and explicit; new skills default to "available to all" unless their META carries a `roles: [...]` hint.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_skill_catalog_renderer.py`:

```python
"""Tests for the skill catalog renderer — role filtering + format."""
from clawbot.skill_catalog_renderer import render_for_role, SkillCatalogEntry


def _entry(name: str, description: str, params: dict, roles: list[str] | None = None) -> SkillCatalogEntry:
    return SkillCatalogEntry(name=name, description=description, params=params, roles=roles or [])


def test_renders_skill_block_with_name_description_params():
    entries = [
        _entry("fs_write", "Write a file to workspace", {"path": "str", "content": "str"}),
    ]
    out = render_for_role("cto", entries)
    assert "fs_write" in out
    assert "Write a file" in out
    assert "path" in out
    assert "content" in out


def test_filters_by_role_when_roles_declared():
    entries = [
        _entry("stripe_issue_card", "Issue card", {"daily_limit_usd": "int"}, roles=["cfo"]),
        _entry("x_post", "Post to X", {"text": "str"}, roles=["cmo"]),
    ]
    cfo_out = render_for_role("cfo", entries)
    cmo_out = render_for_role("cmo", entries)
    assert "stripe_issue_card" in cfo_out
    assert "x_post" not in cfo_out
    assert "x_post" in cmo_out
    assert "stripe_issue_card" not in cmo_out


def test_universal_skills_appear_for_every_role():
    entries = [_entry("time_now", "Get current time", {})]  # no roles → universal
    for role in ("ceo", "cfo", "cmo", "coo", "cto"):
        assert "time_now" in render_for_role(role, entries)


def test_ceo_sees_everything():
    entries = [
        _entry("stripe_issue_card", "Issue card", {}, roles=["cfo"]),
        _entry("x_post", "Post to X", {}, roles=["cmo"]),
        _entry("fs_write", "Write file", {}, roles=["cto"]),
    ]
    out = render_for_role("ceo", entries)
    assert "stripe_issue_card" in out
    assert "x_post" in out
    assert "fs_write" in out


def test_output_is_stable_across_calls():
    """Same inputs must produce identical output — agent prompt diffs would
    cause LLM cache misses and waste tokens."""
    entries = [_entry("a", "a desc", {}), _entry("b", "b desc", {})]
    assert render_for_role("ceo", entries) == render_for_role("ceo", entries)


def test_empty_catalog_returns_empty_marker():
    out = render_for_role("ceo", [])
    assert "no skills" in out.lower()


def test_skill_with_no_params_renders_cleanly():
    entries = [_entry("time_now", "Returns current time", {})]
    out = render_for_role("ceo", entries)
    assert "time_now" in out
    # no trailing comma or empty paren block
    assert "()" not in out or "time_now()" in out
```

- [ ] **Step 2: Run the tests — expect ImportError**

Run: `uv run pytest tests/test_skill_catalog_renderer.py -v`
Expected: `ModuleNotFoundError: No module named 'clawbot.skill_catalog_renderer'`.

- [ ] **Step 3: Implement the renderer**

Create `src/clawbot/skill_catalog_renderer.py`:

```python
"""Renders the skill catalog into a prompt block, filtered by executive role.

The default role-mapping below is a starting point. Skills whose META carries
a `roles` key override the default; skills with empty `roles` are universal.
The CEO always sees the union — the org's most senior agent must reason about
the full action surface."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SkillCatalogEntry:
    name: str
    description: str
    params: dict[str, str]
    roles: list[str]


# Default role visibility for builtin skill prefixes. Skills not matching any
# prefix default to universal (visible to all roles). Skills with explicit
# `roles` in META override this.
_PREFIX_DEFAULTS: dict[str, list[str]] = {
    "stripe_": ["cfo", "ceo"],
    "account_": ["cmo", "cto", "ceo"],
    "x_post": ["cmo", "ceo"],
    "linkedin_": ["cmo", "ceo"],
    "reddit_": ["cmo", "ceo"],
    "email_": ["cmo", "cfo", "ceo"],
    "fs_": ["cto", "ceo"],
    "vector_": ["cto", "ceo"],
    "llm_": ["cto", "cmo", "ceo"],
    "browser_": ["cmo", "cto", "ceo"],
    "sql_": ["cfo", "cto", "ceo"],
    "operator_": ["ceo", "cfo", "cmo", "coo", "cto"],  # everyone can escalate
    "worker_": ["ceo"],  # only CEO hires/fires
    "skill_request": ["cto", "ceo"],
}


def _effective_roles(entry: SkillCatalogEntry) -> list[str]:
    if entry.roles:
        return entry.roles
    for prefix, roles in _PREFIX_DEFAULTS.items():
        if entry.name.startswith(prefix):
            return roles
    return []  # empty list = universal


def render_for_role(role: str, entries: list[SkillCatalogEntry]) -> str:
    """Render a prompt-friendly catalog block for the given role.

    Format:
        Available skills (output as JSON {"action": "<skill_name>", ...params}):
        - skill_name(param1: type, param2: type) — description
        - ...
    """
    if not entries:
        return "Available skills: (no skills currently registered)"

    visible = sorted(
        [e for e in entries if not _effective_roles(e) or role in _effective_roles(e) or role == "ceo"],
        key=lambda e: e.name,
    )
    if not visible:
        return f"Available skills for {role}: (none)"

    lines = ['Available skills (invoke via {"action": "<skill_name>", ...params}):']
    for e in visible:
        if e.params:
            sig = ", ".join(f"{k}: {v}" for k, v in e.params.items())
            lines.append(f'- {e.name}({sig}) — {e.description}')
        else:
            lines.append(f"- {e.name}() — {e.description}")
    return "\n".join(lines)
```

- [ ] **Step 4: Run the tests — expect 7 passing**

Run: `uv run pytest tests/test_skill_catalog_renderer.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/clawbot/skill_catalog_renderer.py tests/test_skill_catalog_renderer.py
git commit -m "feat: skill_catalog_renderer for role-filtered prompt injection" -m "" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: Wire the catalog into the executive cycle prompts

**Files:**
- Modify: `src/clawbot/scheduler.py` (both `_run_executive_cycle` and `_run_lieutenant_cycle`)
- Create: `tests/test_scheduler_skill_injection.py`

Both cycle builders currently hard-code the six action schemas (`hire | fire | assign_task | publish_product | message | wait`). We append a seventh schema `| {"action": "<skill_name>", ...params}` and inject the rendered catalog above it. The renderer pulls from `clawbot.skill_registry.REGISTRY` so the prompt always reflects the live skill set.

- [ ] **Step 1: Write the failing test**

Create `tests/test_scheduler_skill_injection.py`:

```python
"""The executive cycle prompt must include the skill catalog block."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

import pytest


def _make_scheduler(tmp_path: Path):
    """Build a minimally-wired scheduler whose dependencies are mocks. Returns the
    scheduler + the captured pool so tests can inspect the prompt sent to the LLM."""
    from clawbot.scheduler import Scheduler

    bus = MagicMock()
    bus.publish = AsyncMock(return_value="msg-id")
    bus.read_and_ack = AsyncMock(return_value=[])
    pool = MagicMock()
    pool.complete = AsyncMock(return_value='{"action":"wait","directive":"test"}')
    factory = MagicMock()
    brain = MagicMock()
    brain.search = AsyncMock(return_value=[])
    db_pool = MagicMock()

    # Minimal SOUL.md
    agents_dir = tmp_path / "agents"
    (agents_dir / "ceo").mkdir(parents=True)
    (agents_dir / "ceo" / "SOUL.md").write_text("# CEO\nMinimal SOUL for testing.\n")
    (agents_dir / "cto").mkdir(parents=True)
    (agents_dir / "cto" / "SOUL.md").write_text("# CTO\nMinimal SOUL.\n")

    metrics_dir = tmp_path / "metrics"
    metrics_dir.mkdir()
    (metrics_dir / "company.json").write_text('{"revenue_7d_gbp": 0, "worker_count": 0}')

    s = Scheduler(
        pool=pool, bus=bus, brain=brain, factory=factory,
        db_pool=db_pool, agents_dir=agents_dir, metrics_dir=metrics_dir,
    )
    return s, pool


@pytest.mark.asyncio
async def test_executive_cycle_prompt_contains_skill_catalog(tmp_path):
    from clawbot.skill_catalog_renderer import SkillCatalogEntry
    s, pool = _make_scheduler(tmp_path)

    fake_entries = [SkillCatalogEntry(
        name="fs_write", description="Write to workspace",
        params={"path": "str", "content": "str"}, roles=[],
    )]
    with patch("clawbot.scheduler._load_skill_catalog", return_value=fake_entries):
        await s._run_executive_cycle()

    pool.complete.assert_called_once()
    prompt_text = pool.complete.call_args.args[0][1]["content"]
    assert "fs_write" in prompt_text
    assert "Write to workspace" in prompt_text
    assert '"action": "<skill_name>"' in prompt_text


@pytest.mark.asyncio
async def test_lieutenant_cycle_prompt_contains_skill_catalog(tmp_path):
    from clawbot.skill_catalog_renderer import SkillCatalogEntry
    s, pool = _make_scheduler(tmp_path)

    fake_entries = [SkillCatalogEntry(
        name="stripe_issue_card", description="Issue Stripe card",
        params={"cardholder_id": "str", "daily_limit_usd": "int", "agent_id": "str"},
        roles=["cfo"],
    )]
    (tmp_path / "agents" / "cfo").mkdir()
    (tmp_path / "agents" / "cfo" / "SOUL.md").write_text("# CFO\n")
    with patch("clawbot.scheduler._load_skill_catalog", return_value=fake_entries):
        await s._run_lieutenant_cycle("cfo")

    pool.complete.assert_called_once()
    prompt_text = pool.complete.call_args.args[0][1]["content"]
    assert "stripe_issue_card" in prompt_text
    assert "cardholder_id" in prompt_text


@pytest.mark.asyncio
async def test_cfo_does_not_see_cmo_only_skills(tmp_path):
    from clawbot.skill_catalog_renderer import SkillCatalogEntry
    s, pool = _make_scheduler(tmp_path)

    fake_entries = [SkillCatalogEntry(
        name="x_post", description="Post to X", params={"text": "str"}, roles=["cmo"],
    )]
    (tmp_path / "agents" / "cfo").mkdir()
    (tmp_path / "agents" / "cfo" / "SOUL.md").write_text("# CFO\n")
    with patch("clawbot.scheduler._load_skill_catalog", return_value=fake_entries):
        await s._run_lieutenant_cycle("cfo")
    prompt_text = pool.complete.call_args.args[0][1]["content"]
    assert "x_post" not in prompt_text
```

- [ ] **Step 2: Run tests — expect failure**

Run: `uv run pytest tests/test_scheduler_skill_injection.py -v`
Expected: AttributeError on `_load_skill_catalog` or AssertionError on `"fs_write" in prompt_text`.

- [ ] **Step 3: Add the catalog loader to scheduler.py**

In `src/clawbot/scheduler.py`, near the top (after the existing imports), add:

```python
def _load_skill_catalog() -> list:
    """Snapshot of the registered skills as catalog entries. Called per cycle
    so newly-registered skills become available without restarting.

    Returns an empty list if the registry hasn't initialised — the renderer
    handles the empty case gracefully."""
    from clawbot.skill_registry import REGISTRY
    from clawbot.skill_catalog_renderer import SkillCatalogEntry
    if REGISTRY is None:
        return []
    out: list[SkillCatalogEntry] = []
    for name in REGISTRY.list_names():
        meta = REGISTRY.get_meta(name)
        if meta is None:
            continue
        # META may carry a `roles` hint we honour; default to empty (universal).
        roles = []
        # SkillMeta is a frozen dataclass without `roles`; check the raw module
        # would require re-reading the file, so honour the prefix default in the
        # renderer instead. Future: extend SkillMeta to carry `roles`.
        out.append(SkillCatalogEntry(
            name=meta.name,
            description=meta.description,
            params=meta.params,
            roles=roles,
        ))
    return out
```

- [ ] **Step 4: Update the CEO prompt to include the catalog**

In `src/clawbot/scheduler.py`, locate `_run_executive_cycle` (around line 342). Replace the `messages = [...]` block (currently lines 354-373) with:

```python
        catalog_block = ""
        try:
            from clawbot.skill_catalog_renderer import render_for_role
            entries = _load_skill_catalog()
            catalog_block = "\n\n" + render_for_role("ceo", entries) + "\n"
        except Exception as exc:
            logger.warning("Skill catalog render failed (continuing without it): %s", exc)

        messages = [
            {"role": "system", "content": soul},
            {
                "role": "user",
                "content": (
                    f"Current metrics:\n{json.dumps(metrics, indent=2)}"
                    f"{board_directive}{recent_decisions}"
                    f"{catalog_block}"
                    "\nWhat is your next action? Output JSON with one of these action schemas:\n"
                    '{"action": "hire", "role": "...", "mandate": "...", "supervisor": "..."} '
                    '| {"action": "fire", "agent_id": "..."} '
                    '| {"action": "assign_task", "assigned_to": "<agent_id>", "title": "...", "description": "..."} '
                    '| {"action": "publish_product", "title": "...", "description": "..."} '
                    '| {"action": "message", "target": "<agent_id>", "message": "..."} '
                    '| {"action": "wait", "directive": "reason"} '
                    '| {"action": "<skill_name>", ...params per the skill catalog above}\n'
                    'Add: "priority": "high|medium|low", "next_wakeup_s": <integer 60-1800> '
                    "(how many seconds until your next cycle), "
                    '"escalate": null | {"severity": "info|request|warning|urgent", "summary": "...", "detail": "..."}'
                ),
            },
        ]
```

- [ ] **Step 5: Mirror the change in the lieutenant cycle**

In `src/clawbot/scheduler.py`, locate `_run_lieutenant_cycle` (around line 515). Replace its `messages = [...]` block (around lines 524-541) with the analogous structure — note the role is `agent_id` (the lieutenant) not `"ceo"`:

```python
        catalog_block = ""
        try:
            from clawbot.skill_catalog_renderer import render_for_role
            entries = _load_skill_catalog()
            catalog_block = "\n\n" + render_for_role(agent_id, entries) + "\n"
        except Exception as exc:
            logger.warning("Skill catalog render failed for %s (continuing): %s", agent_id, exc)

        messages = [
            {"role": "system", "content": soul},
            {
                "role": "user",
                "content": (
                    f"Current metrics:\n{json.dumps(metrics, indent=2)}"
                    f"{catalog_block}"
                    "\nWhat is your next action? Output JSON with one of these action schemas:\n"
                    '{"action": "hire", "role": "...", "mandate": "...", "supervisor": "..."} '
                    '| {"action": "fire", "agent_id": "..."} '
                    '| {"action": "assign_task", "assigned_to": "<agent_id>", "title": "...", "description": "..."} '
                    '| {"action": "publish_product", "title": "...", "description": "..."} '
                    '| {"action": "message", "target": "<agent_id>", "message": "..."} '
                    '| {"action": "wait", "directive": "reason"} '
                    '| {"action": "<skill_name>", ...params per the skill catalog above}\n'
                    'Add: "priority": "high|medium|low", "next_wakeup_s": <integer 60-1800> '
                    "(how many seconds until your next cycle), "
                    '"escalate": null | {"severity": "info|request|warning|urgent", "summary": "...", "detail": "..."}'
                ),
            },
        ]
```

- [ ] **Step 6: Run tests — expect passing**

Run: `uv run pytest tests/test_scheduler_skill_injection.py -v`
Expected: 3 passed.

- [ ] **Step 7: Sanity-check no regression on the broader suite**

Run: `uv run pytest tests/test_scheduler.py tests/test_scheduler_widgets.py tests/test_scheduler_selfschedule.py -v`
Expected: all green (these test other scheduler concerns; the prompt change shouldn't break them).

- [ ] **Step 8: Commit**

```bash
git add src/clawbot/scheduler.py tests/test_scheduler_skill_injection.py
git commit -m "feat: inject role-filtered skill catalog into executive prompts" -m "" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: `plans` table schema and async store

**Files:**
- Modify: `src/clawbot/db.py` (add the table to `init_schema`)
- Create: `src/clawbot/plan_store.py`
- Create: `tests/test_plan_store.py`

A plan is a chain of milestones for one agent. Each row is one milestone, with its hypothesis, success criteria, evidence collected so far, and status. The "current" milestone is the lowest-indexed `status='active'` row for the agent.

Schema:
```sql
CREATE TABLE IF NOT EXISTS plans (
    plan_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    milestone_idx INTEGER NOT NULL,
    hypothesis TEXT NOT NULL,
    success_criteria TEXT NOT NULL,  -- JSON list of criteria
    evidence TEXT NOT NULL DEFAULT '[]',  -- JSON list of evidence items
    status TEXT NOT NULL DEFAULT 'active',  -- active | done | pivoted | abandoned
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (agent_id, plan_id, milestone_idx)
)
```

- [ ] **Step 1: Write the failing tests**

Create `tests/test_plan_store.py`:

```python
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
```

- [ ] **Step 2: Run — expect import failure**

Run: `uv run pytest tests/test_plan_store.py -v`
Expected: ImportError on `clawbot.plan_store`.

- [ ] **Step 3: Add the schema to db.py**

In `src/clawbot/db.py`, find the function that calls `CREATE TABLE` for existing tables (e.g. the schema-init body). Add this CREATE TABLE statement alongside the others:

```python
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS plans (
                plan_id TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                milestone_idx INTEGER NOT NULL,
                hypothesis TEXT NOT NULL,
                success_criteria TEXT NOT NULL,
                evidence TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'active',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (agent_id, plan_id, milestone_idx)
            )
        """)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_plans_agent_status "
            "ON plans(agent_id, status, milestone_idx)"
        )
```

- [ ] **Step 4: Implement PlanStore**

Create `src/clawbot/plan_store.py`:

```python
"""Async CRUD over the plans table.

Plans persist multi-cycle commitments per executive. The current milestone is
the lowest-indexed `status='active'` row for the agent. Advancing closes the
current milestone (status='done') and unblocks the next one; pivoting closes
the entire current plan (status='pivoted') and creates a new plan_id chain."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MilestoneRow:
    plan_id: str
    agent_id: str
    milestone_idx: int
    hypothesis: str
    success_criteria: str  # JSON
    evidence: str          # JSON
    status: str


class PlanStore:
    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def init_schema(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS plans (
                    plan_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    milestone_idx INTEGER NOT NULL,
                    hypothesis TEXT NOT NULL,
                    success_criteria TEXT NOT NULL,
                    evidence TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (agent_id, plan_id, milestone_idx)
                )
            """)
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_plans_agent_status "
                "ON plans(agent_id, status, milestone_idx)"
            )

    async def create_plan(
        self, *, agent_id: str, hypothesis: str, milestones: list[dict],
    ) -> str:
        """Create a fresh plan chain. Returns the new plan_id.

        Each milestone is `{"hypothesis": str, "success_criteria": list[str]}`.
        The first milestone is marked active; subsequent ones are pending."""
        plan_id = uuid.uuid4().hex
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                for idx, m in enumerate(milestones):
                    status = "active" if idx == 0 else "pending"
                    await conn.execute(
                        "INSERT INTO plans (plan_id, agent_id, milestone_idx, hypothesis, "
                        "success_criteria, evidence, status) VALUES ($1, $2, $3, $4, $5, '[]', $6)",
                        plan_id, agent_id, idx, m["hypothesis"],
                        json.dumps(m["success_criteria"]), status,
                    )
        return plan_id

    async def get_current_milestone(self, *, agent_id: str) -> MilestoneRow | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT plan_id, agent_id, milestone_idx, hypothesis, success_criteria, "
                "evidence, status FROM plans WHERE agent_id=$1 AND status='active' "
                "ORDER BY milestone_idx ASC LIMIT 1",
                agent_id,
            )
        if row is None:
            return None
        return MilestoneRow(**dict(row))

    async def advance_milestone(self, *, agent_id: str) -> bool:
        """Close current milestone, activate next pending one. Returns True if
        a next milestone was activated, False if the plan is now complete."""
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                current = await conn.fetchrow(
                    "SELECT plan_id, milestone_idx FROM plans WHERE agent_id=$1 "
                    "AND status='active' ORDER BY milestone_idx ASC LIMIT 1 FOR UPDATE",
                    agent_id,
                )
                if current is None:
                    return False
                await conn.execute(
                    "UPDATE plans SET status='done', updated_at=NOW() "
                    "WHERE agent_id=$1 AND plan_id=$2 AND milestone_idx=$3",
                    agent_id, current["plan_id"], current["milestone_idx"],
                )
                next_row = await conn.fetchrow(
                    "SELECT milestone_idx FROM plans WHERE agent_id=$1 AND plan_id=$2 "
                    "AND status='pending' ORDER BY milestone_idx ASC LIMIT 1 FOR UPDATE",
                    agent_id, current["plan_id"],
                )
                if next_row is None:
                    return False
                await conn.execute(
                    "UPDATE plans SET status='active', updated_at=NOW() "
                    "WHERE agent_id=$1 AND plan_id=$2 AND milestone_idx=$3",
                    agent_id, current["plan_id"], next_row["milestone_idx"],
                )
        return True

    async def add_evidence(self, *, agent_id: str, item: dict) -> None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                current = await conn.fetchrow(
                    "SELECT plan_id, milestone_idx, evidence FROM plans "
                    "WHERE agent_id=$1 AND status='active' ORDER BY milestone_idx ASC LIMIT 1 FOR UPDATE",
                    agent_id,
                )
                if current is None:
                    return
                items = json.loads(current["evidence"])
                items.append(item)
                await conn.execute(
                    "UPDATE plans SET evidence=$1, updated_at=NOW() "
                    "WHERE agent_id=$2 AND plan_id=$3 AND milestone_idx=$4",
                    json.dumps(items), agent_id, current["plan_id"], current["milestone_idx"],
                )

    async def pivot(
        self, *, agent_id: str, reason: str,
        new_hypothesis: str, new_milestones: list[dict],
    ) -> str:
        """Mark all of the agent's current-plan rows as pivoted; create a new plan."""
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                current = await conn.fetchrow(
                    "SELECT plan_id FROM plans WHERE agent_id=$1 AND status IN ('active','pending') "
                    "ORDER BY milestone_idx ASC LIMIT 1 FOR UPDATE",
                    agent_id,
                )
                if current is not None:
                    await conn.execute(
                        "UPDATE plans SET status='pivoted', updated_at=NOW() "
                        "WHERE agent_id=$1 AND plan_id=$2",
                        agent_id, current["plan_id"],
                    )
        return await self.create_plan(
            agent_id=agent_id, hypothesis=new_hypothesis, milestones=new_milestones,
        )
```

- [ ] **Step 5: Run — expect passing**

Run: `uv run pytest tests/test_plan_store.py -v`
Expected: 6 passed if Postgres is reachable, else `SKIPPED` (the conditional is intentional — `operating_facts.md` documents asyncpg unavailability locally).

- [ ] **Step 6: Commit**

```bash
git add src/clawbot/db.py src/clawbot/plan_store.py tests/test_plan_store.py
git commit -m "feat: plans table + PlanStore for multi-cycle agent commitments" -m "" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: Plan-state injection into executive cycles + plan-update action handlers

**Files:**
- Modify: `src/clawbot/scheduler.py` (cycle prompts include current milestone state; cycle response post-parsed for plan-related fields)
- Modify: `src/clawbot/directive_router.py` (three new handlers: `plan_init`, `plan_advance`, `plan_pivot`)
- Create: `tests/test_scheduler_plan_integration.py`

Each executive cycle now does three things in addition to the existing flow:
1. **Read** the agent's current milestone before LLM call; inject into prompt.
2. **LLM** decides one of: `plan_init` (if no current plan), `plan_advance` (criteria met), `plan_pivot` (criteria unmet, hypothesis wrong), or any normal action (with the understanding the action is in service of the current milestone).
3. **Write** any `evidence` field emitted by the LLM to the milestone before the next cycle.

The router gains three handlers that mutate the plan via PlanStore.

- [ ] **Step 1: Write the failing test**

Create `tests/test_scheduler_plan_integration.py`:

```python
"""End-to-end: cycle reads plan → injects to prompt → router updates on response."""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

import pytest


def _scheduler_with_plan_mock(tmp_path: Path, agent_id: str, milestone: dict | None):
    from clawbot.scheduler import Scheduler

    bus = MagicMock()
    bus.publish = AsyncMock(return_value="msg-id")
    bus.read_and_ack = AsyncMock(return_value=[])
    pool = MagicMock()
    pool.complete = AsyncMock(return_value='{"action":"wait","directive":"test"}')
    factory = MagicMock()
    brain = MagicMock(); brain.search = AsyncMock(return_value=[])
    db_pool = MagicMock()

    agents_dir = tmp_path / "agents"
    (agents_dir / agent_id).mkdir(parents=True)
    (agents_dir / agent_id / "SOUL.md").write_text(f"# {agent_id}\n")
    metrics_dir = tmp_path / "metrics"
    metrics_dir.mkdir()
    (metrics_dir / "company.json").write_text('{"revenue_7d_gbp": 0}')

    s = Scheduler(
        pool=pool, bus=bus, brain=brain, factory=factory,
        db_pool=db_pool, agents_dir=agents_dir, metrics_dir=metrics_dir,
    )
    return s, pool


@pytest.mark.asyncio
async def test_cycle_prompt_includes_current_milestone(tmp_path):
    s, pool = _scheduler_with_plan_mock(tmp_path, "cmo", None)

    fake_milestone = MagicMock()
    fake_milestone.milestone_idx = 0
    fake_milestone.hypothesis = "Substack pilot — 3 posts in 7 days"
    fake_milestone.success_criteria = json.dumps(["3 posts published", "subs > 0"])
    fake_milestone.evidence = json.dumps([{"kind": "skill_call", "skill": "fs_write"}])

    plan_store_mock = MagicMock()
    plan_store_mock.get_current_milestone = AsyncMock(return_value=fake_milestone)

    with patch("clawbot.scheduler.PlanStore", return_value=plan_store_mock):
        await s._run_lieutenant_cycle("cmo")

    prompt_text = pool.complete.call_args.args[0][1]["content"]
    assert "Substack pilot" in prompt_text
    assert "3 posts published" in prompt_text
    assert "skill_call" in prompt_text


@pytest.mark.asyncio
async def test_cycle_prompt_signals_no_plan_when_none(tmp_path):
    s, pool = _scheduler_with_plan_mock(tmp_path, "cmo", None)
    plan_store_mock = MagicMock()
    plan_store_mock.get_current_milestone = AsyncMock(return_value=None)
    with patch("clawbot.scheduler.PlanStore", return_value=plan_store_mock):
        await s._run_lieutenant_cycle("cmo")
    prompt_text = pool.complete.call_args.args[0][1]["content"]
    assert "no active plan" in prompt_text.lower()


@pytest.mark.asyncio
async def test_plan_init_action_creates_plan_in_store():
    from clawbot.directive_router import DirectiveRouter
    bus = MagicMock(); bus.publish = AsyncMock()
    factory = MagicMock(); brain = MagicMock()
    router = DirectiveRouter(
        bus=bus, factory=factory, brain=brain,
        metrics_dir=Path("/tmp/test_metrics"),
    )
    plan_store_mock = MagicMock()
    plan_store_mock.create_plan = AsyncMock(return_value="plan_abc")
    router._plan_store = plan_store_mock

    await router._handle_plan_init(
        data={
            "action": "plan_init",
            "hypothesis": "Substack pilot",
            "milestones": [
                {"hypothesis": "3 posts in 7 days", "success_criteria": ["3 posts"]},
            ],
        },
        chain_id="c", from_agent="cmo",
    )
    plan_store_mock.create_plan.assert_called_once()
    kwargs = plan_store_mock.create_plan.call_args.kwargs
    assert kwargs["agent_id"] == "cmo"
    assert kwargs["hypothesis"] == "Substack pilot"
```

- [ ] **Step 2: Run — expect failure**

Run: `uv run pytest tests/test_scheduler_plan_integration.py -v`
Expected: AttributeError on `clawbot.scheduler.PlanStore` (not yet imported) or on `router._handle_plan_init`.

- [ ] **Step 3: Update the lieutenant cycle to inject plan state**

In `src/clawbot/scheduler.py`, in `_run_lieutenant_cycle` (modified in Task 2), insert plan-loading just after `metrics = await self._load_metrics()` and before the prompt-build block:

```python
        from clawbot.plan_store import PlanStore
        plan_store = PlanStore(self._db_pool)
        current_milestone = None
        try:
            current_milestone = await plan_store.get_current_milestone(agent_id=agent_id)
        except Exception as exc:
            logger.warning("plan load for %s failed (continuing without): %s", agent_id, exc)

        if current_milestone is None:
            plan_block = "\n\nNo active plan. Output {\"action\":\"plan_init\", \"hypothesis\":\"...\", \"milestones\":[{\"hypothesis\":\"...\",\"success_criteria\":[\"...\"]}]} to commit to one before any other action.\n"
        else:
            plan_block = (
                f"\n\nCurrent milestone (#{current_milestone.milestone_idx}): "
                f"{current_milestone.hypothesis}\n"
                f"Success criteria: {current_milestone.success_criteria}\n"
                f"Evidence collected so far: {current_milestone.evidence}\n"
                "When the criteria are met, output {\"action\":\"plan_advance\"}. "
                "When the hypothesis is invalidated, output "
                "{\"action\":\"plan_pivot\", \"reason\":\"...\", \"new_hypothesis\":\"...\", "
                "\"new_milestones\":[...]}. "
                "Otherwise pick any action that gathers evidence toward the criteria.\n"
            )
```

Then in the existing `messages = [...]` block (from Task 2), change the user-message content to include `{plan_block}` after `{catalog_block}`:

```python
                    f"Current metrics:\n{json.dumps(metrics, indent=2)}"
                    f"{catalog_block}"
                    f"{plan_block}"
                    "\nWhat is your next action? Output JSON with one of these action schemas:\n"
                    '{"action": "plan_init", "hypothesis": "...", "milestones": [...]} '
                    '| {"action": "plan_advance"} '
                    '| {"action": "plan_pivot", "reason": "...", "new_hypothesis": "...", "new_milestones": [...]} '
                    '| {"action": "hire", "role": "...", "mandate": "...", "supervisor": "..."} '
                    '| {"action": "fire", "agent_id": "..."} '
                    # ... rest unchanged
```

- [ ] **Step 4: Mirror in the CEO cycle**

Apply the same plan-block injection to `_run_executive_cycle`. The CEO's plan-update actions are the same three (`plan_init`, `plan_advance`, `plan_pivot`).

- [ ] **Step 5: Add the router handlers**

In `src/clawbot/directive_router.py`, register `_handle_plan_init`, `_handle_plan_advance`, `_handle_plan_pivot` in `_get_handler`'s `hardcoded` dict:

```python
        hardcoded = {
            "hire": self._handle_hire,
            "fire": self._handle_fire,
            "assign_task": self._handle_assign_task,
            "publish_product": self._handle_publish_product,
            "message": self._handle_message_action,
            "web_research": self._handle_web_research,
            "plan_init": self._handle_plan_init,
            "plan_advance": self._handle_plan_advance,
            "plan_pivot": self._handle_plan_pivot,
        }
```

And define the three handler methods on `DirectiveRouter`:

```python
    async def _handle_plan_init(self, data: dict, chain_id: str, from_agent: str) -> None:
        from clawbot.plan_store import PlanStore
        store = getattr(self, "_plan_store", None) or PlanStore(getattr(self, "_db_pool", None))
        hypothesis = str(data.get("hypothesis", ""))[:400]
        milestones = data.get("milestones", [])
        if not isinstance(milestones, list) or not milestones:
            raise ValueError("plan_init requires non-empty milestones list")
        await store.create_plan(
            agent_id=from_agent, hypothesis=hypothesis, milestones=milestones,
        )
        logger.info("Plan initialised for %s with %d milestones", from_agent, len(milestones))

    async def _handle_plan_advance(self, data: dict, chain_id: str, from_agent: str) -> None:
        from clawbot.plan_store import PlanStore
        store = getattr(self, "_plan_store", None) or PlanStore(getattr(self, "_db_pool", None))
        advanced = await store.advance_milestone(agent_id=from_agent)
        logger.info("Plan advance for %s: %s", from_agent, "next milestone active" if advanced else "plan complete")

    async def _handle_plan_pivot(self, data: dict, chain_id: str, from_agent: str) -> None:
        from clawbot.plan_store import PlanStore
        store = getattr(self, "_plan_store", None) or PlanStore(getattr(self, "_db_pool", None))
        reason = str(data.get("reason", ""))[:400]
        new_hypothesis = str(data.get("new_hypothesis", ""))[:400]
        new_milestones = data.get("new_milestones", [])
        if not new_milestones:
            raise ValueError("plan_pivot requires new_milestones")
        await store.pivot(
            agent_id=from_agent, reason=reason,
            new_hypothesis=new_hypothesis, new_milestones=new_milestones,
        )
        logger.info("Plan pivot for %s: %s", from_agent, reason[:80])
```

- [ ] **Step 6: Run tests — expect passing**

Run: `uv run pytest tests/test_scheduler_plan_integration.py -v`
Expected: 3 passed.

- [ ] **Step 7: Sanity broader suite**

Run: `uv run pytest tests/test_scheduler.py tests/test_directive_router.py tests/test_directive_router_skills.py -v`
Expected: green.

- [ ] **Step 8: Commit**

```bash
git add src/clawbot/scheduler.py src/clawbot/directive_router.py tests/test_scheduler_plan_integration.py
git commit -m "feat: plans injected into cycles; plan_init/advance/pivot routed" -m "" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: `active_hypothesis` table + HypothesisStore

**Files:**
- Modify: `src/clawbot/db.py`
- Create: `src/clawbot/hypothesis_store.py`
- Create: `tests/test_hypothesis_store.py`

One row per company-wide hypothesis ever attempted. Exactly one row has `status='active'` at any time. Generated by the board on PIVOT/RESET outcomes (Task 6).

Schema:
```sql
CREATE TABLE IF NOT EXISTS active_hypothesis (
    hypothesis_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    kill_criteria TEXT NOT NULL,  -- JSON: {"max_days_without_revenue": int, "min_qualified_leads_by_day": [day, count], ...}
    status TEXT NOT NULL,  -- active | killed | superseded
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    killed_at TIMESTAMPTZ
)
```

- [ ] **Step 1: Write the failing tests**

Create `tests/test_hypothesis_store.py`:

```python
"""active_hypothesis table CRUD — only one row active at a time."""
import json
import pytest
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
async def test_init_schema_creates_table(pool):
    from clawbot.hypothesis_store import HypothesisStore
    store = HypothesisStore(pool)
    await store.init_schema()


@pytest.mark.asyncio
async def test_set_active_marks_previous_superseded(pool):
    from clawbot.hypothesis_store import HypothesisStore
    store = HypothesisStore(pool)
    await store.init_schema()
    await store.set_active(name="H1", description="£9 IR35 PDF",
                            kill_criteria={"max_days_without_revenue": 14})
    await store.set_active(name="H2", description="B2B research briefs",
                            kill_criteria={"max_days_without_revenue": 21})
    active = await store.get_active()
    assert active is not None
    assert active["name"] == "H2"
    history = await store.list_history()
    assert any(h["name"] == "H1" and h["status"] == "superseded" for h in history)


@pytest.mark.asyncio
async def test_kill_active_clears_active_row(pool):
    from clawbot.hypothesis_store import HypothesisStore
    store = HypothesisStore(pool)
    await store.init_schema()
    await store.set_active(name="H1", description="x", kill_criteria={})
    await store.kill_active(reason="0 conversions by day 14")
    assert await store.get_active() is None
```

- [ ] **Step 2: Run — expect failure**

Run: `uv run pytest tests/test_hypothesis_store.py -v`
Expected: ImportError.

- [ ] **Step 3: Add schema to db.py**

In `src/clawbot/db.py`'s schema-init body, alongside the `plans` CREATE TABLE from Task 3:

```python
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS active_hypothesis (
                hypothesis_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                kill_criteria TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                killed_at TIMESTAMPTZ
            )
        """)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_hypothesis_status ON active_hypothesis(status)"
        )
```

- [ ] **Step 4: Implement HypothesisStore**

Create `src/clawbot/hypothesis_store.py`:

```python
"""Single source of truth for the company's currently-active strategic bet.

Exactly one row has status='active' at any time. set_active() supersedes the
previous active row. kill_active() marks the active row killed (no new active).
The board writes to this store; the CEO reads it as a strategic constraint."""
from __future__ import annotations

import json
import uuid
from typing import Any


class HypothesisStore:
    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def init_schema(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS active_hypothesis (
                    hypothesis_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    kill_criteria TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    killed_at TIMESTAMPTZ
                )
            """)
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_hypothesis_status ON active_hypothesis(status)"
            )

    async def set_active(self, *, name: str, description: str, kill_criteria: dict) -> str:
        new_id = uuid.uuid4().hex
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "UPDATE active_hypothesis SET status='superseded' WHERE status='active'"
                )
                await conn.execute(
                    "INSERT INTO active_hypothesis (hypothesis_id, name, description, kill_criteria, status) "
                    "VALUES ($1, $2, $3, $4, 'active')",
                    new_id, name, description, json.dumps(kill_criteria),
                )
        return new_id

    async def get_active(self) -> dict | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT hypothesis_id, name, description, kill_criteria, status, created_at "
                "FROM active_hypothesis WHERE status='active' LIMIT 1"
            )
        if row is None:
            return None
        return {
            "hypothesis_id": row["hypothesis_id"],
            "name": row["name"],
            "description": row["description"],
            "kill_criteria": json.loads(row["kill_criteria"]),
            "status": row["status"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        }

    async def list_history(self) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT hypothesis_id, name, description, status, created_at, killed_at "
                "FROM active_hypothesis ORDER BY created_at DESC"
            )
        return [
            {"hypothesis_id": r["hypothesis_id"], "name": r["name"],
             "description": r["description"], "status": r["status"]}
            for r in rows
        ]

    async def kill_active(self, *, reason: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE active_hypothesis SET status='killed', killed_at=NOW() "
                "WHERE status='active'"
            )
```

- [ ] **Step 5: Run — expect 3 passing (or skipped if no Postgres)**

Run: `uv run pytest tests/test_hypothesis_store.py -v`

- [ ] **Step 6: Commit**

```bash
git add src/clawbot/db.py src/clawbot/hypothesis_store.py tests/test_hypothesis_store.py
git commit -m "feat: active_hypothesis table + HypothesisStore" -m "" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 6: Board PIVOT → new hypothesis generation

**Files:**
- Modify: `src/clawbot/board.py` (when outcome is PIVOT or RESET, write a new active_hypothesis row)
- Modify: `src/clawbot/scheduler.py` (CEO cycle reads active_hypothesis and includes it as strategic context)
- Create: `tests/test_board_hypothesis_pivot.py`

The board already votes CONTINUE / PIVOT / RESET. PIVOT triggers `requires_ceo_action=True` and an `action_required` text. We extend this: when PIVOT or RESET, the board generates a new hypothesis via a one-shot LLM call seeded with the resolution rationale and writes it via HypothesisStore. The CEO's cycle reads the active hypothesis and treats it as the operating constraint — everything cascades from there.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_board_hypothesis_pivot.py`:

```python
"""Board PIVOT outcome generates a new active_hypothesis."""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


@pytest.mark.asyncio
async def test_pivot_outcome_generates_new_hypothesis():
    from clawbot.board import generate_hypothesis_from_pivot

    pool = MagicMock()
    pool.complete = AsyncMock(return_value=json.dumps({
        "name": "H2",
        "description": "B2B research briefs sold to early-stage VCs at £500-2000 each",
        "kill_criteria": {"max_days_without_revenue": 21, "min_outreach_replies_by_day": [14, 2]},
    }))

    store_mock = MagicMock()
    store_mock.set_active = AsyncMock(return_value="hyp_abc")

    new_id = await generate_hypothesis_from_pivot(
        pool=pool,
        store=store_mock,
        previous_name="H1",
        previous_description="£9 IR35 PDF on Gumroad",
        pivot_rationale="0 sales after 14 days; market saturated with free LLM-generated PDFs",
    )
    assert new_id == "hyp_abc"
    store_mock.set_active.assert_called_once()
    kwargs = store_mock.set_active.call_args.kwargs
    assert kwargs["name"] == "H2"
    assert "B2B" in kwargs["description"]
    assert kwargs["kill_criteria"]["max_days_without_revenue"] == 21


@pytest.mark.asyncio
async def test_ceo_cycle_prompt_includes_active_hypothesis(tmp_path):
    """CEO sees the active hypothesis as a top-level strategic constraint."""
    from clawbot.scheduler import Scheduler
    bus = MagicMock(); bus.publish = AsyncMock(); bus.read_and_ack = AsyncMock(return_value=[])
    pool = MagicMock(); pool.complete = AsyncMock(return_value='{"action":"wait"}')
    factory = MagicMock(); brain = MagicMock(); brain.search = AsyncMock(return_value=[])
    db_pool = MagicMock()
    agents_dir = tmp_path / "agents"
    (agents_dir / "ceo").mkdir(parents=True)
    (agents_dir / "ceo" / "SOUL.md").write_text("# CEO\n")
    metrics_dir = tmp_path / "metrics"
    metrics_dir.mkdir()
    (metrics_dir / "company.json").write_text('{"revenue_7d_gbp": 0}')
    s = Scheduler(pool=pool, bus=bus, brain=brain, factory=factory,
                   db_pool=db_pool, agents_dir=agents_dir, metrics_dir=metrics_dir)

    hyp_store_mock = MagicMock()
    hyp_store_mock.get_active = AsyncMock(return_value={
        "name": "H2", "description": "B2B research briefs",
        "kill_criteria": {"max_days_without_revenue": 21},
        "status": "active",
    })
    with patch("clawbot.scheduler.HypothesisStore", return_value=hyp_store_mock):
        await s._run_executive_cycle()

    prompt_text = pool.complete.call_args.args[0][1]["content"]
    assert "H2" in prompt_text
    assert "B2B research briefs" in prompt_text
```

- [ ] **Step 2: Run — expect failure**

Run: `uv run pytest tests/test_board_hypothesis_pivot.py -v`

- [ ] **Step 3: Add the hypothesis generator to board.py**

In `src/clawbot/board.py`, append at module level:

```python
GENERATE_HYPOTHESIS_PROMPT = """\
You are the board of an autonomous AI company. The current strategic hypothesis
has been voted down. You must propose the next one.

Previous hypothesis: {previous_name} — {previous_description}
Pivot rationale: {pivot_rationale}

Propose a NEW hypothesis that:
1. Materially differs from the previous one (don't propose a near-duplicate)
2. Has a clear kill criterion so it can be falsified in 14-21 days
3. Plays to the company's strengths: LLM synthesis at scale, browser automation,
   autonomous email and payments, but limited by zero existing audience and no
   credit history for paid ads
4. Has unit economics that could plausibly reach £2k/month within 60 days

Output ONLY JSON in this shape, no preamble:
{{
  "name": "H<N>",
  "description": "1-2 sentence description of the bet",
  "kill_criteria": {{
    "max_days_without_revenue": <int>,
    "min_outreach_replies_by_day": [<day>, <count>],
    "min_qualified_leads_by_day": [<day>, <count>]
  }}
}}
"""


async def generate_hypothesis_from_pivot(
    *, pool, store, previous_name: str, previous_description: str, pivot_rationale: str,
) -> str:
    """LLM-generate a new hypothesis based on the board's pivot rationale and
    write it to the active_hypothesis store. Returns the new hypothesis_id."""
    messages = [
        {"role": "system", "content": "You are the board of an autonomous AI company. Output only valid JSON."},
        {"role": "user", "content": GENERATE_HYPOTHESIS_PROMPT.format(
            previous_name=previous_name,
            previous_description=previous_description,
            pivot_rationale=pivot_rationale,
        )},
    ]
    raw = await pool.complete(messages, tier="executive", max_tokens=600)
    data = json.loads(raw)
    return await store.set_active(
        name=str(data["name"])[:40],
        description=str(data["description"])[:400],
        kill_criteria=data.get("kill_criteria", {}),
    )
```

- [ ] **Step 4: Wire into the board's resolution flow**

Find where board resolutions with `outcome='PIVOT'` are handled (the board publishes a `board.resolution` message; the scheduler consumes it). In `scheduler.py`, locate the `_board_resolution_listener` loop (search for `board.resolution`). After caching the resolution, when outcome is PIVOT or RESET, call `generate_hypothesis_from_pivot`:

```python
                if msg.get("outcome") in ("PIVOT", "RESET"):
                    try:
                        from clawbot.board import generate_hypothesis_from_pivot
                        from clawbot.hypothesis_store import HypothesisStore
                        hyp_store = HypothesisStore(self._db_pool)
                        current = await hyp_store.get_active()
                        prev_name = current["name"] if current else "H1"
                        prev_desc = current["description"] if current else "Initial hypothesis"
                        await generate_hypothesis_from_pivot(
                            pool=self._pool, store=hyp_store,
                            previous_name=prev_name, previous_description=prev_desc,
                            pivot_rationale=msg.get("action_required", "")[:400],
                        )
                    except Exception as exc:
                        logger.error("Hypothesis generation on pivot failed: %s", exc)
```

- [ ] **Step 5: Inject active_hypothesis into the CEO prompt**

In `_run_executive_cycle`, after `board_directive = self._latest_board_directive()`, add:

```python
        active_hyp_block = ""
        try:
            from clawbot.hypothesis_store import HypothesisStore
            hyp_store = HypothesisStore(self._db_pool)
            active = await hyp_store.get_active()
            if active is not None:
                active_hyp_block = (
                    f"\n\nACTIVE HYPOTHESIS ({active['name']}): {active['description']}\n"
                    f"Kill criteria: {active['kill_criteria']}\n"
                    "Every decision you make must serve this hypothesis. If you believe "
                    "the kill criteria are met or the bet is broken, escalate to the board "
                    "for a PIVOT vote.\n"
                )
        except Exception as exc:
            logger.warning("Active hypothesis load failed (continuing): %s", exc)
```

Then in the `messages` block, include `{active_hyp_block}` after `{board_directive}`.

- [ ] **Step 6: Run — expect 2 passing**

Run: `uv run pytest tests/test_board_hypothesis_pivot.py -v`

- [ ] **Step 7: Sanity broader board tests**

Run: `uv run pytest tests/test_board.py -v`
Expected: green.

- [ ] **Step 8: Commit**

```bash
git add src/clawbot/board.py src/clawbot/scheduler.py tests/test_board_hypothesis_pivot.py
git commit -m "feat: board PIVOT generates new active_hypothesis; CEO cycle reads it" -m "" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 7: Seed H1 into the active_hypothesis store on first deploy

**Files:**
- Modify: `src/clawbot/main.py` (one-time seed if no active hypothesis exists at startup)
- Create: `tests/test_hypothesis_seed.py`

Without a seed, the CEO sees "no active hypothesis" forever — the board only generates one on PIVOT, which requires a previous hypothesis to pivot from. Seed H1 (the £9 IR35 PDF) at startup if and only if the store is empty.

- [ ] **Step 1: Write the failing test**

Create `tests/test_hypothesis_seed.py`:

```python
"""Startup seed inserts H1 only when no hypothesis is active yet."""
import asyncio
from unittest.mock import AsyncMock, MagicMock


def test_seed_only_when_store_empty():
    from clawbot.main import maybe_seed_h1
    store = MagicMock()
    store.get_active = AsyncMock(return_value=None)
    store.set_active = AsyncMock(return_value="hyp_seed")
    result = asyncio.run(maybe_seed_h1(store))
    assert result is True
    store.set_active.assert_called_once()


def test_seed_skipped_when_active_exists():
    from clawbot.main import maybe_seed_h1
    store = MagicMock()
    store.get_active = AsyncMock(return_value={"name": "H1", "status": "active"})
    store.set_active = AsyncMock()
    result = asyncio.run(maybe_seed_h1(store))
    assert result is False
    store.set_active.assert_not_called()
```

- [ ] **Step 2: Implement the seed**

In `src/clawbot/main.py`, add (near other startup helpers):

```python
async def maybe_seed_h1(store) -> bool:
    """Insert the initial H1 hypothesis if none is active. Returns True if seeded."""
    current = await store.get_active()
    if current is not None:
        return False
    await store.set_active(
        name="H1",
        description="£9 IR35 contractor status assessment PDF sold on Gumroad. "
                    "Distribution via Substack newsletter and LinkedIn. "
                    "Operator (Harry) creates the Gumroad product manually; agents do drafting and distribution.",
        kill_criteria={
            "max_days_without_revenue": 14,
            "min_qualified_leads_by_day": [7, 3],
        },
    )
    return True
```

Call it during startup, after the DB pool is created:

```python
    # After existing pool init:
    from clawbot.hypothesis_store import HypothesisStore
    hyp_store = HypothesisStore(db_pool)
    await hyp_store.init_schema()
    if await maybe_seed_h1(hyp_store):
        logger.info("Seeded initial hypothesis H1")
```

- [ ] **Step 3: Run — expect passing**

Run: `uv run pytest tests/test_hypothesis_seed.py -v`

- [ ] **Step 4: Commit**

```bash
git add src/clawbot/main.py tests/test_hypothesis_seed.py
git commit -m "feat: seed H1 active_hypothesis on first startup" -m "" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 8: End-to-end verification + operator notes

**Files:**
- Modify: `C:\ClaudeShared\memory\projects\clawbot\operating_facts.md`

End-to-end check after all preceding tasks land. Confirm:
1. Cycle prompts contain catalog + plan block + (CEO only) hypothesis block.
2. The router's plan_* handlers fire when the LLM outputs them.
3. The board's PIVOT flow generates a new hypothesis row.
4. The seed runs once on startup.

- [ ] **Step 1: Run the full test suite locally**

Run: `uv run pytest --tb=line 2>&1 | tail -10`
Expected: ≥ (previous count) + the new tests; the only failures are the pre-existing 2 asyncpg failures documented in `operating_facts.md`.

- [ ] **Step 2: Deploy to VPS**

Push the branch, run the standard deploy command. Watch the logs after restart for:
- `"Seeded initial hypothesis H1"` (one-time)
- The first executive cycle that includes the new prompt blocks (any non-message action like `fs_write` or `vector_search` is a success signal).

- [ ] **Step 3: Append OODA-loop note to operating_facts.md**

```markdown

## OODA loop closure (added 2026-05-18)

The executive cycle previously generated zero skill calls because the prompt did not enumerate skills. After this phase:

- **Layer 1 — skill catalog:** every cycle's prompt now contains a role-filtered skill catalog (renderer in `src/clawbot/skill_catalog_renderer.py`). CFO sees payments/stripe; CMO sees social/account/email; CTO sees fs/coder/llm; CEO sees the union.
- **Layer 2 — plans:** each executive has a multi-cycle plan in the `plans` table. Cycle prompts include current milestone + evidence collected. Three new actions: `plan_init`, `plan_advance`, `plan_pivot`.
- **Layer 3 — active hypothesis:** single source of truth in `active_hypothesis` table. CEO cycle reads it. Board PIVOT outcomes generate the next one via an LLM call seeded with the resolution rationale. H1 is seeded at first startup.

**What to watch in the first 24h after deploy:**
- `skill_calls` table should accumulate non-zero rows (was 0/day before).
- `plans` table should accumulate rows from `plan_init` actions.
- Telegram channel for any escalations during plan execution.

**Pre-existing 60-day kill clock interpretation:** invalidated. The previous clock was measuring "can clawbot generate revenue from a strategy nobody is executing." The new clock starts when first non-message action lands. If the loop is closed but revenue is still zero after 21 days under H1, that's a real signal — the board should generate H2.
```

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/plans/2026-05-18-close-the-ooda-loop.md
git commit -m "docs: OODA loop closure plan + operator runbook update" -m "" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Acceptance Criteria (binary — all must pass, then stop)

- [ ] `uv run pytest` shows ≥ previous count + the new tests, with only the 2 pre-existing asyncpg failures unchanged
- [ ] A fresh `make_noop_ctx()`-based cycle test confirms the executive prompt now contains the skill catalog block
- [ ] After deploy, the `skill_calls` table on the VPS accumulates at least one non-zero row within 24 hours of restart (concrete proof the loop closed)
- [ ] The `plans` table accumulates at least one row from a `plan_init` action within 24 hours
- [ ] `active_hypothesis` table contains exactly one `status='active'` row after startup
- [ ] No regression: existing tests for skill_ctx, accounts, payments, social, email, scheduler, board all still pass
- [ ] Operator runbook in `operating_facts.md` documents the new tables and the new prompt structure

When all pass: done. Do not add more "loop refinements" until 14 days of production data are collected — the next round of fixes is data-driven, not speculative.

---

## What this plan does NOT do (and why that's correct)

This plan does not tell the agents what business to run, what skill to call first, or how to deploy capital. It changes the substrate from "agents that can only deliberate" to "agents that can execute, commit to plans, and pivot." After this, the question shifts from *"why aren't the agents acting?"* to *"are the agents' actions producing valuable outcomes?"* — a much more answerable question because it has actual data behind it.

If after 14 days of OODA-loop operation under H1 the answer is "no, actions are happening but revenue is zero," the board will pivot to H2 autonomously and we'll get a second data point. The substrate's job is to make that experiment cycle fast and cheap. This plan does that and nothing more.
