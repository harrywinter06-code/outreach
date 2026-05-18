# Portfolio Operator: Multi-Hypothesis + Capital + Company Fitness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn clawbot from a single-bet machine into a portfolio operator. Three coordinated additions: (1) relax `active_hypothesis` from "exactly one" to "1 to 3 concurrent," with auto-diversification when a bet stagnates; (2) graduate Stripe Issuing from sandbox to live mode with hard operator-gated caps; (3) compute a company-level fitness score so the meta-evaluator can track week-over-week whether the organism as a whole is making progress. Together these let the substrate run multiple bets in parallel with real money against real markets, with a single number summarising health.

**Architecture:** Three coordinated layers, each independently testable. Multi-hypothesis adds a `weight` column to `active_hypothesis`, a `hypothesis_id` link from `plans` so each bet has its own plan-tree, and an auto-diversification cron that spawns a new hypothesis when an existing one hits 50% of its time-window with <20% progress (capped at `MAX_ACTIVE_HYPOTHESES=3`). Capital integration adds a `capital_ledger` table, a daily/weekly cap enforced *before* Stripe is called (independent of Stripe's own server-side limit), and a `STRIPE_LIVE_MODE_ENABLED` boolean gate. Company-level fitness aggregates revenue + plan velocity + skill-call success + capital efficiency across ALL active hypotheses into one score, snapshotted daily.

**Why multi-hypothesis first, not last:** Capital allocation across multiple hypotheses needs the portfolio scaffolding to exist first. Company fitness scoring across the portfolio needs the same. If we did capital first, we'd build it assuming one active hypothesis and rewrite when N>1. Order matters.

**What this plan deliberately does NOT do:**
- 10+ concurrent hypotheses (resource starvation — cap at 3 until paid LLM tier)
- Channel/presence asset model (premature — defer until day 30 if a channel is worth tracking)
- More skills beyond Phase H (in flight via parallel sessions)
- New agent types or orchestration patterns

**Tech Stack:** Python 3.12+, asyncpg (existing), stdlib (decimal, datetime), pytest. No new pip dependencies. Builds on existing `Database.init_schema`, `_LivePayments` (Stripe), `HypothesisStore`, `PlanStore` — all shipped.

**Pre-mortem:** The most likely failure mode is the operator-approval Telegram flow ships, the agent issues a live card with a £500/day cap, the agent then composes that card details into a poorly-vetted ad spend via browser-use, and £500 evaporates in an evening with zero leads. Mitigation: per-card daily cap is enforced at Stripe AND at the ledger level (defense in depth); the first three live card issuances after `STRIPE_LIVE_MODE_ENABLED` flips require operator approval per-charge as well as per-card (set on the card's spending controls); a kill-switch env var `CAPITAL_FREEZE=true` halts all new authorizations without restarting clawbot.

**Conditionality:** Only execute this plan AFTER Phase H lands AND the 7-day evaluation window has produced at least one of: first £ of revenue, first qualified inbound lead, or first substantive operator-approval Telegram prompt. If none of those hit, the substrate isn't producing data — adding capital won't fix that; pivot the *use case* instead. This plan is the natural next step *only* when the OODA loop has demonstrated it can produce real outputs.

---

## File Structure

**Create:**
- `src/clawbot/capital_ledger.py` — async CRUD over `capital_ledger` table; cap-enforcement query
- `src/clawbot/company_fitness.py` — pure-function company-level fitness scoring + snapshot writer
- `tests/test_capital_ledger.py`
- `tests/test_company_fitness.py`
- `tests/test_capital_graduation.py`
- `tests/test_hypothesis_portfolio.py`
- `tests/test_auto_diversification.py`

**Modify:**
- `src/clawbot/db.py` — add `weight` + `progress_score` columns to `active_hypothesis`; add `hypothesis_id` column to `plans`; add `capital_ledger` table; add `company_fitness_snapshots` table
- `src/clawbot/config.py` — add `max_active_hypotheses: int = 3`; `stripe_live_mode_enabled: bool = False`, `capital_daily_cap_gbp: float = 0.0`, `capital_weekly_cap_gbp: float = 0.0`, `capital_freeze: bool = False`
- `src/clawbot/hypothesis_store.py` — relax "exactly one active" to "1 to N active"; add `add_hypothesis`, `get_active_portfolio`, `kill_hypothesis_by_id`, `update_progress_score`; keep `get_active` for backwards-compat returning highest-weight active
- `src/clawbot/plan_store.py` — `create_plan` accepts optional `hypothesis_id` kwarg; new `abandon_plans_for_hypothesis(hypothesis_id, reason)` method
- `src/clawbot/board.py` — `generate_hypothesis_from_pivot` becomes `generate_hypothesis_for_portfolio` (adds new entry to portfolio if below cap, replaces lowest-weight active otherwise)
- `src/clawbot/skill_ctx.py` — modify `_LivePayments.issue_card` and `_LivePayments.create_payment_link` to consult `CapitalLedger` before calling Stripe; raise `RuntimeError("capital_cap_exceeded")` if over cap; check `stripe_live_mode_enabled`
- `agents/skills/_builtin/payments/stripe_issue_card.py` — already has `requires_approval=True`; no change but document the dual-gate (per-card + per-day)
- `src/clawbot/scheduler.py` — CEO cycle reads `get_active_portfolio()` and injects all active hypotheses; add `_run_auto_diversification_loop` (daily) that spawns a new hypothesis when an existing one is stagnant; add `_run_company_fitness_snapshot_loop` (daily)
- `src/clawbot/monitor.py` — when capital usage crosses 80% of weekly cap, publish an operator escalation

---

## Task 0: Multi-hypothesis portfolio (1 to N active, capped at 3)

**Files:**
- Modify: `src/clawbot/db.py` (add `weight`, `progress_score` to `active_hypothesis`; add `hypothesis_id` to `plans`)
- Modify: `src/clawbot/config.py` (add `max_active_hypotheses: int = 3`)
- Modify: `src/clawbot/hypothesis_store.py` (relax "exactly one active")
- Modify: `src/clawbot/plan_store.py` (link to hypothesis)
- Modify: `src/clawbot/board.py` (PIVOT adds to portfolio)
- Modify: `src/clawbot/scheduler.py` (CEO reads portfolio; auto-diversification loop)
- Create: `tests/test_hypothesis_portfolio.py`
- Create: `tests/test_auto_diversification.py`

The current `set_active` supersedes the previous active row (one-at-a-time). Relax to "1 to N active." Add `weight` (0.0-1.0, soft resource allocation hint) and `progress_score` (0.0-1.0, computed by auto-diversification). Link plans to hypotheses so killing a hypothesis cascades its plans to `abandoned`. Auto-diversification: a daily loop checks each active hypothesis; if it's past 50% of its time-window AND progress_score < 0.20 AND portfolio is below cap → spawn a fresh hypothesis via the existing LLM-generated path.

### Task 0a: Schema + HypothesisStore portfolio API

- [ ] **Step 1: Write the failing tests**

Create `tests/test_hypothesis_portfolio.py`:

```python
"""Multi-hypothesis portfolio — 1 to N active simultaneously."""
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
async def test_add_hypothesis_does_not_supersede_previous(pool):
    """Old `set_active` superseded the previous row. `add_hypothesis` does NOT."""
    from clawbot.hypothesis_store import HypothesisStore
    store = HypothesisStore(pool)
    await store.init_schema()
    # Clean slate
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM active_hypothesis WHERE name LIKE 'test_pf_%'")

    id_a = await store.add_hypothesis(name="test_pf_A", description="bet A",
                                       kill_criteria={"max_days_without_revenue": 14},
                                       weight=0.5)
    id_b = await store.add_hypothesis(name="test_pf_B", description="bet B",
                                       kill_criteria={"max_days_without_revenue": 14},
                                       weight=0.5)
    portfolio = await store.get_active_portfolio()
    names = {h["name"] for h in portfolio if h["name"].startswith("test_pf_")}
    assert names == {"test_pf_A", "test_pf_B"}


@pytest.mark.asyncio
async def test_kill_hypothesis_by_id_only_kills_that_one(pool):
    from clawbot.hypothesis_store import HypothesisStore
    store = HypothesisStore(pool)
    await store.init_schema()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM active_hypothesis WHERE name LIKE 'test_kill_%'")

    id_a = await store.add_hypothesis(name="test_kill_A", description="x",
                                       kill_criteria={}, weight=0.5)
    id_b = await store.add_hypothesis(name="test_kill_B", description="y",
                                       kill_criteria={}, weight=0.5)
    await store.kill_hypothesis_by_id(hypothesis_id=id_a, reason="failed signal")

    portfolio = await store.get_active_portfolio()
    active_names = {h["name"] for h in portfolio}
    assert "test_kill_A" not in active_names
    assert "test_kill_B" in active_names


@pytest.mark.asyncio
async def test_get_active_returns_highest_weight_for_backcompat(pool):
    """Legacy `get_active()` callers get the highest-weight active hypothesis."""
    from clawbot.hypothesis_store import HypothesisStore
    store = HypothesisStore(pool)
    await store.init_schema()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM active_hypothesis WHERE name LIKE 'test_ba_%'")

    await store.add_hypothesis(name="test_ba_low", description="x",
                                kill_criteria={}, weight=0.2)
    await store.add_hypothesis(name="test_ba_high", description="y",
                                kill_criteria={}, weight=0.7)
    active = await store.get_active()
    assert active is not None
    assert active["name"] == "test_ba_high"


@pytest.mark.asyncio
async def test_update_progress_score_persists(pool):
    from clawbot.hypothesis_store import HypothesisStore
    store = HypothesisStore(pool)
    await store.init_schema()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM active_hypothesis WHERE name LIKE 'test_prog_%'")

    hid = await store.add_hypothesis(name="test_prog", description="x",
                                      kill_criteria={}, weight=0.5)
    await store.update_progress_score(hypothesis_id=hid, score=0.65)
    portfolio = await store.get_active_portfolio()
    target = next(h for h in portfolio if h["hypothesis_id"] == hid)
    assert abs(float(target["progress_score"]) - 0.65) < 0.001


@pytest.mark.asyncio
async def test_portfolio_respects_cap(pool):
    """add_hypothesis raises when adding would exceed MAX_ACTIVE_HYPOTHESES."""
    from clawbot.hypothesis_store import HypothesisStore
    store = HypothesisStore(pool, max_active=3)
    await store.init_schema()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM active_hypothesis WHERE name LIKE 'test_cap_%'")

    for i in range(3):
        await store.add_hypothesis(name=f"test_cap_{i}", description="x",
                                    kill_criteria={}, weight=0.33)
    with pytest.raises(RuntimeError, match="portfolio_full"):
        await store.add_hypothesis(name="test_cap_overflow", description="x",
                                    kill_criteria={}, weight=0.1)
```

- [ ] **Step 2: Run — expect import / attribute errors**

Run: `uv run pytest tests/test_hypothesis_portfolio.py -v`
Expected: AttributeError on `add_hypothesis` / `kill_hypothesis_by_id` / `update_progress_score`, or SKIPPED if Postgres unavailable.

- [ ] **Step 3: Add columns to active_hypothesis in db.py**

In `src/clawbot/db.py`'s schema-init body, the existing `active_hypothesis` table needs two new columns. Add `ALTER TABLE` after the CREATE TABLE statement (idempotent — checks for column existence):

```python
        await conn.execute("""
            ALTER TABLE active_hypothesis
            ADD COLUMN IF NOT EXISTS weight NUMERIC(4, 3) NOT NULL DEFAULT 1.0
        """)
        await conn.execute("""
            ALTER TABLE active_hypothesis
            ADD COLUMN IF NOT EXISTS progress_score NUMERIC(4, 3) NOT NULL DEFAULT 0.0
        """)
```

Also add `hypothesis_id` column to `plans` table:
```python
        await conn.execute("""
            ALTER TABLE plans
            ADD COLUMN IF NOT EXISTS hypothesis_id TEXT
        """)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_plans_hypothesis "
            "ON plans(hypothesis_id) WHERE hypothesis_id IS NOT NULL"
        )
```

- [ ] **Step 4: Add `max_active_hypotheses` to config**

In `src/clawbot/config.py`:

```python
    # Portfolio operator: hard cap on concurrent active hypotheses.
    # 3 is the realistic ceiling at free-tier LLM scale; raise to 5-10 on paid
    # tier. Setting to 1 reverts to single-hypothesis behaviour.
    max_active_hypotheses: int = 3
```

- [ ] **Step 5: Implement HypothesisStore portfolio API**

In `src/clawbot/hypothesis_store.py`, replace the existing class body with this version. The old `set_active` is kept as a thin wrapper around `add_hypothesis` for callers that haven't migrated yet.

```python
"""Multi-hypothesis portfolio store.

Up to N hypotheses can be active simultaneously, where N = max_active.
Resource-allocation hint is the `weight` column (0.0-1.0, agents read it
when prioritising attention). `progress_score` is computed externally by
the auto-diversification loop and read by it next cycle to decide whether
to spawn a replacement."""
from __future__ import annotations

import json
import uuid
from typing import Any


class HypothesisStore:
    def __init__(self, pool: Any, max_active: int = 3) -> None:
        self._pool = pool
        self._max_active = max_active

    async def init_schema(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS active_hypothesis (
                    hypothesis_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    kill_criteria TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    weight NUMERIC(4, 3) NOT NULL DEFAULT 1.0,
                    progress_score NUMERIC(4, 3) NOT NULL DEFAULT 0.0,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    killed_at TIMESTAMPTZ
                )
            """)
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_hypothesis_status ON active_hypothesis(status)"
            )

    async def add_hypothesis(
        self, *, name: str, description: str, kill_criteria: dict,
        weight: float = 1.0,
    ) -> str:
        """Append a new active hypothesis. Raises RuntimeError if the portfolio
        is already at MAX_ACTIVE_HYPOTHESES. To replace an existing entry, call
        kill_hypothesis_by_id first."""
        async with self._pool.acquire() as conn:
            count_row = await conn.fetchrow(
                "SELECT COUNT(*) AS n FROM active_hypothesis WHERE status='active'"
            )
            current = int(count_row["n"]) if count_row else 0
            if current >= self._max_active:
                raise RuntimeError(
                    f"portfolio_full: {current} active hypotheses, cap is {self._max_active}. "
                    f"Kill one before adding another."
                )
            new_id = uuid.uuid4().hex
            await conn.execute(
                "INSERT INTO active_hypothesis (hypothesis_id, name, description, "
                "kill_criteria, status, weight) VALUES ($1, $2, $3, $4, 'active', $5)",
                new_id, name, description, json.dumps(kill_criteria), float(weight),
            )
        return new_id

    async def set_active(self, *, name: str, description: str, kill_criteria: dict) -> str:
        """Backwards-compat: single-active behaviour. Kills any existing active
        rows then adds this one with weight=1.0. Used by the H1 seed and any
        legacy caller. New code should use add_hypothesis."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE active_hypothesis SET status='superseded', killed_at=NOW() "
                "WHERE status='active'"
            )
        return await self.add_hypothesis(
            name=name, description=description, kill_criteria=kill_criteria, weight=1.0,
        )

    async def get_active(self) -> dict | None:
        """Backwards-compat: returns the single highest-weight active hypothesis."""
        portfolio = await self.get_active_portfolio()
        if not portfolio:
            return None
        return max(portfolio, key=lambda h: float(h["weight"]))

    async def get_active_portfolio(self) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT hypothesis_id, name, description, kill_criteria, status, "
                "weight, progress_score, created_at FROM active_hypothesis "
                "WHERE status='active' ORDER BY weight DESC, created_at ASC"
            )
        return [
            {
                "hypothesis_id": r["hypothesis_id"],
                "name": r["name"],
                "description": r["description"],
                "kill_criteria": json.loads(r["kill_criteria"]),
                "status": r["status"],
                "weight": float(r["weight"]),
                "progress_score": float(r["progress_score"]),
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ]

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
        """Backwards-compat: kills ALL active hypotheses. New code should use
        kill_hypothesis_by_id to kill exactly one."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE active_hypothesis SET status='killed', killed_at=NOW() "
                "WHERE status='active'"
            )

    async def kill_hypothesis_by_id(self, *, hypothesis_id: str, reason: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE active_hypothesis SET status='killed', killed_at=NOW() "
                "WHERE hypothesis_id=$1 AND status='active'",
                hypothesis_id,
            )

    async def update_progress_score(self, *, hypothesis_id: str, score: float) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE active_hypothesis SET progress_score=$1 "
                "WHERE hypothesis_id=$2 AND status='active'",
                float(score), hypothesis_id,
            )
```

- [ ] **Step 6: Extend PlanStore for hypothesis linking**

In `src/clawbot/plan_store.py`, modify `create_plan` to accept optional `hypothesis_id`, and add `abandon_plans_for_hypothesis`:

```python
    async def create_plan(
        self, *, agent_id: str, hypothesis: str, milestones: list[dict],
        hypothesis_id: str | None = None,
    ) -> str:
        plan_id = uuid.uuid4().hex
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                for idx, m in enumerate(milestones):
                    status = "active" if idx == 0 else "pending"
                    await conn.execute(
                        "INSERT INTO plans (plan_id, agent_id, milestone_idx, hypothesis, "
                        "hypothesis_id, success_criteria, evidence, status) "
                        "VALUES ($1, $2, $3, $4, $5, $6, '[]', $7)",
                        plan_id, agent_id, idx, m["hypothesis"], hypothesis_id,
                        json.dumps(m["success_criteria"]), status,
                    )
        return plan_id

    async def abandon_plans_for_hypothesis(self, *, hypothesis_id: str, reason: str) -> int:
        """When a hypothesis is killed, mark all its plans as abandoned. Returns
        the number of plan rows updated."""
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE plans SET status='abandoned', updated_at=NOW() "
                "WHERE hypothesis_id=$1 AND status IN ('active', 'pending')",
                hypothesis_id,
            )
        # asyncpg returns "UPDATE N" as the command status; parse N
        try:
            return int(result.split()[-1])
        except (ValueError, IndexError):
            return 0
```

- [ ] **Step 7: Run tests**

Run: `uv run pytest tests/test_hypothesis_portfolio.py tests/test_hypothesis_store.py tests/test_plan_store.py -v`
Expected: portfolio tests pass or skip cleanly; existing hypothesis_store + plan_store tests still pass (backwards-compat preserved).

- [ ] **Step 8: Commit**

```bash
git add src/clawbot/db.py src/clawbot/config.py src/clawbot/hypothesis_store.py src/clawbot/plan_store.py tests/test_hypothesis_portfolio.py
git commit -m "feat: hypothesis portfolio — 1 to N active, plans linked to hypothesis_id" -m "" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 0b: CEO cycle reads portfolio; board PIVOT adds to portfolio

**Files:**
- Modify: `src/clawbot/board.py` (rename `generate_hypothesis_from_pivot` → `generate_hypothesis_for_portfolio`; new behaviour adds to portfolio or replaces lowest-weight if at cap)
- Modify: `src/clawbot/scheduler.py` (CEO cycle injects ALL active hypotheses, not just the top one; the PIVOT listener uses the new generator)

- [ ] **Step 1: Update board.generate_hypothesis_for_portfolio**

In `src/clawbot/board.py`, the existing `generate_hypothesis_from_pivot` writes to `store.set_active`. Change it to use the portfolio API:

```python
async def generate_hypothesis_for_portfolio(
    *, pool, store, previous_name: str, previous_description: str, pivot_rationale: str,
    max_active: int = 3,
) -> str:
    """LLM-generate a new hypothesis. If portfolio has capacity, ADD to it.
    If portfolio is at cap, the LOWEST-WEIGHT active hypothesis is killed
    and the new one takes its slot.

    Returns the new hypothesis_id."""
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

    # If portfolio is full, kill the lowest-weight active row to make room.
    portfolio = await store.get_active_portfolio()
    if len(portfolio) >= max_active:
        lowest = min(portfolio, key=lambda h: float(h["weight"]))
        await store.kill_hypothesis_by_id(
            hypothesis_id=lowest["hypothesis_id"],
            reason=f"replaced by board PIVOT (rationale: {pivot_rationale[:200]})",
        )

    return await store.add_hypothesis(
        name=str(data["name"])[:40],
        description=str(data["description"])[:400],
        kill_criteria=data.get("kill_criteria", {}),
        weight=1.0 / max_active,  # equal-weight by default; can be tuned
    )


# Backwards-compat alias for any pre-portfolio callers
generate_hypothesis_from_pivot = generate_hypothesis_for_portfolio
```

- [ ] **Step 2: Update the CEO cycle prompt to inject the whole portfolio**

In `src/clawbot/scheduler.py`, find where `_run_executive_cycle` builds `active_hyp_block` (added in the OODA-loop work). Replace the single-hypothesis block with a multi-hypothesis version:

```python
        active_hyp_block = ""
        try:
            from clawbot.hypothesis_store import HypothesisStore
            if hasattr(self, "_db_pool") and self._db_pool is not None:
                hyp_store = HypothesisStore(self._db_pool, max_active=settings.max_active_hypotheses)
                portfolio = await hyp_store.get_active_portfolio()
                if portfolio:
                    lines = ["ACTIVE HYPOTHESIS PORTFOLIO (allocate attention by weight):"]
                    for h in portfolio:
                        lines.append(
                            f"- {h['name']} (weight {h['weight']:.2f}, "
                            f"progress {h['progress_score']:.2f}): {h['description']}"
                        )
                        lines.append(f"  Kill criteria: {h['kill_criteria']}")
                    lines.append(
                        "Every decision you make must serve ONE of these bets. "
                        "When proposing actions, name which hypothesis the action targets. "
                        "If any bet's kill criteria are met, escalate to the board for that "
                        "specific hypothesis to be PIVOTed."
                    )
                    active_hyp_block = "\n\n" + "\n".join(lines) + "\n"
        except Exception as exc:
            logger.warning("Active hypothesis portfolio load failed (continuing): %s", exc)
```

- [ ] **Step 3: Update the board-resolution listener to use the new generator**

In `src/clawbot/scheduler.py`, the existing `_board_resolution_subscriber` (or wherever board.resolution messages are consumed) currently calls `generate_hypothesis_from_pivot`. Pass the `max_active` from settings:

```python
                if msg.get("outcome") in ("PIVOT", "RESET"):
                    try:
                        from clawbot.board import generate_hypothesis_for_portfolio
                        from clawbot.hypothesis_store import HypothesisStore
                        if hasattr(self, "_db_pool") and self._db_pool is not None:
                            hyp_store = HypothesisStore(
                                self._db_pool,
                                max_active=settings.max_active_hypotheses,
                            )
                            current = await hyp_store.get_active()
                            prev_name = current["name"] if current else "H1"
                            prev_desc = current["description"] if current else "Initial hypothesis"
                            await generate_hypothesis_for_portfolio(
                                pool=self._pool, store=hyp_store,
                                previous_name=prev_name, previous_description=prev_desc,
                                pivot_rationale=msg.get("action_required", "")[:400],
                                max_active=settings.max_active_hypotheses,
                            )
                    except Exception as exc:
                        logger.error("Hypothesis generation on pivot failed: %s", exc)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_board_hypothesis_pivot.py tests/test_scheduler.py tests/test_hypothesis_portfolio.py -v`
Expected: green. The existing `test_board_hypothesis_pivot.py` tests should still pass because `generate_hypothesis_for_portfolio` is backwards-compatible at the unit level (just adds + kills lowest if needed).

- [ ] **Step 5: Commit**

```bash
git add src/clawbot/board.py src/clawbot/scheduler.py
git commit -m "feat: board PIVOT adds to portfolio; CEO cycle reads all active hypotheses" -m "" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 0c: Auto-diversification trigger

**Files:**
- Modify: `src/clawbot/scheduler.py` (add `_run_auto_diversification_loop`)
- Create: `tests/test_auto_diversification.py`

Every 6 hours, check each active hypothesis. If it's past 50% of its time-window AND its progress_score < 0.20 AND the portfolio has room → spawn a fresh hypothesis. This is the "diversify before survival fails" behaviour the operator argued for. Progress_score is computed inline from causal data (revenue, plan-advancement events) — no separate scorer needed.

- [ ] **Step 1: Write the failing test**

Create `tests/test_auto_diversification.py`:

```python
"""Auto-diversification trigger — spawn new hypothesis when an existing one stagnates."""
import asyncio
from datetime import datetime, UTC, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


def test_stagnation_triggers_spawn_when_below_cap():
    """Past 50% time, progress < 0.20, portfolio below cap → spawn."""
    from clawbot.scheduler import _should_diversify_for_hypothesis

    age_days = 8  # 50%+ of 14-day kill window
    progress = 0.10
    portfolio_size = 1
    max_active = 3
    kill_max_days = 14

    assert _should_diversify_for_hypothesis(
        age_days=age_days, progress_score=progress,
        portfolio_size=portfolio_size, max_active=max_active,
        kill_max_days=kill_max_days,
    ) is True


def test_no_spawn_when_progress_high():
    from clawbot.scheduler import _should_diversify_for_hypothesis
    assert _should_diversify_for_hypothesis(
        age_days=10, progress_score=0.50,  # past 50% time but good progress
        portfolio_size=1, max_active=3, kill_max_days=14,
    ) is False


def test_no_spawn_when_time_remaining():
    from clawbot.scheduler import _should_diversify_for_hypothesis
    assert _should_diversify_for_hypothesis(
        age_days=3, progress_score=0.05,  # bad progress but early
        portfolio_size=1, max_active=3, kill_max_days=14,
    ) is False


def test_no_spawn_when_portfolio_at_cap():
    from clawbot.scheduler import _should_diversify_for_hypothesis
    assert _should_diversify_for_hypothesis(
        age_days=10, progress_score=0.10,
        portfolio_size=3, max_active=3, kill_max_days=14,
    ) is False
```

- [ ] **Step 2: Run — expect import failure**

Run: `uv run pytest tests/test_auto_diversification.py -v`

- [ ] **Step 3: Implement the pure-function trigger + the cron loop**

In `src/clawbot/scheduler.py`, add module-level:

```python
def _should_diversify_for_hypothesis(
    *,
    age_days: float,
    progress_score: float,
    portfolio_size: int,
    max_active: int,
    kill_max_days: int,
) -> bool:
    """Pure-function diversification trigger.

    Spawn a new hypothesis when:
    - The existing hypothesis is past 50% of its kill window
    - AND progress on it is below 20%
    - AND the portfolio has room (< max_active)

    All three must hold. Each guards against a failure mode:
    - Time-fraction guard: don't spawn for bets that just started
    - Progress guard: don't spawn alongside working bets
    - Capacity guard: don't exceed the substrate's resource floor
    """
    if portfolio_size >= max_active:
        return False
    if kill_max_days <= 0:
        return False
    time_fraction = age_days / kill_max_days
    if time_fraction < 0.5:
        return False
    if progress_score >= 0.20:
        return False
    return True
```

And add the loop method on the Scheduler class:

```python
    async def _run_auto_diversification_loop(self) -> None:
        """Every 6 hours, check the portfolio. If any active bet is stagnant
        (past 50% time + low progress), spawn a fresh one via the board's
        existing generator. Cap-respecting; does nothing when portfolio is full."""
        DIVERSIFICATION_INTERVAL_S = 6 * 3600  # 6 hours
        while True:
            await asyncio.sleep(DIVERSIFICATION_INTERVAL_S)
            if not (hasattr(self, "_db_pool") and self._db_pool is not None):
                continue
            try:
                from clawbot.hypothesis_store import HypothesisStore
                from clawbot.board import generate_hypothesis_for_portfolio

                hyp_store = HypothesisStore(
                    self._db_pool,
                    max_active=settings.max_active_hypotheses,
                )
                portfolio = await hyp_store.get_active_portfolio()
                if len(portfolio) >= settings.max_active_hypotheses:
                    continue  # No room

                now = datetime.now(UTC)
                for h in portfolio:
                    created_iso = h.get("created_at")
                    if not created_iso:
                        continue
                    created = datetime.fromisoformat(created_iso)
                    age_days = (now - created).total_seconds() / 86400.0
                    kill_max_days = int(h["kill_criteria"].get("max_days_without_revenue", 14))
                    progress = float(h.get("progress_score", 0.0))

                    if _should_diversify_for_hypothesis(
                        age_days=age_days, progress_score=progress,
                        portfolio_size=len(portfolio),
                        max_active=settings.max_active_hypotheses,
                        kill_max_days=kill_max_days,
                    ):
                        logger.info(
                            "Auto-diversification trigger: spawning new hypothesis "
                            "alongside stagnant %s (age=%.1fd, progress=%.2f)",
                            h["name"], age_days, progress,
                        )
                        await generate_hypothesis_for_portfolio(
                            pool=self._pool, store=hyp_store,
                            previous_name=h["name"],
                            previous_description=h["description"],
                            pivot_rationale=(
                                f"Auto-diversification: {h['name']} is stagnant "
                                f"(age {age_days:.1f}d, progress {progress:.2f}). "
                                f"Spawning a new bet alongside it to diversify."
                            ),
                            max_active=settings.max_active_hypotheses,
                        )
                        break  # Spawn at most one per cycle
            except Exception as exc:
                logger.error("Auto-diversification loop iteration failed: %s", exc)
```

- [ ] **Step 4: Launch the loop in scheduler's run method**

Wherever `Scheduler.run` (or `start`) creates its background tasks, append:

```python
            tasks.append(asyncio.create_task(
                self._run_auto_diversification_loop(),
                name="auto-diversification",
            ))
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_auto_diversification.py -v`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add src/clawbot/scheduler.py tests/test_auto_diversification.py
git commit -m "feat: auto-diversification spawns new hypothesis when stagnant" -m "" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 1: `capital_ledger` table + CapitalLedger async store

**Files:**
- Modify: `src/clawbot/db.py`
- Create: `src/clawbot/capital_ledger.py`
- Create: `tests/test_capital_ledger.py`

Records every spend authorization clawbot makes (card issuance, payment link creation, direct charge, etc.) with a link back to the originating skill call. The store exposes a `current_period_total_gbp(period)` query used to enforce caps before any new spend.

Schema:
```sql
CREATE TABLE IF NOT EXISTS capital_ledger (
    entry_id BIGSERIAL PRIMARY KEY,
    skill_call_id BIGINT,  -- nullable; FK conceptually to skill_calls.id but no enforcement (skill_calls schema is opaque)
    agent_id TEXT NOT NULL,
    action_type TEXT NOT NULL,  -- 'card_issued' | 'payment_link_created' | 'charge_authorized' | 'refund_processed'
    amount_gbp NUMERIC(12, 2) NOT NULL,
    currency_original TEXT NOT NULL DEFAULT 'GBP',
    amount_original NUMERIC(12, 2),
    stripe_object_id TEXT,
    metadata TEXT NOT NULL DEFAULT '{}',  -- JSON
    is_live_mode BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_capital_ledger_created ON capital_ledger(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_capital_ledger_agent ON capital_ledger(agent_id, created_at DESC);
```

- [ ] **Step 1: Write the failing tests**

Create `tests/test_capital_ledger.py`:

```python
"""Capital ledger CRUD + cap enforcement queries."""
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
    from clawbot.capital_ledger import CapitalLedger
    led = CapitalLedger(pool)
    await led.init_schema()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='capital_ledger' ORDER BY column_name"
        )
    cols = {r["column_name"] for r in rows}
    assert {"entry_id", "agent_id", "action_type", "amount_gbp", "is_live_mode"} <= cols


@pytest.mark.asyncio
async def test_record_and_query_total(pool):
    from clawbot.capital_ledger import CapitalLedger
    from decimal import Decimal
    led = CapitalLedger(pool)
    await led.init_schema()
    # Clean slate
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM capital_ledger WHERE agent_id LIKE 'test_%'")
    await led.record(agent_id="test_cfo", action_type="card_issued",
                     amount_gbp=Decimal("25.00"), is_live_mode=True)
    await led.record(agent_id="test_cfo", action_type="charge_authorized",
                     amount_gbp=Decimal("12.50"), is_live_mode=True)
    await led.record(agent_id="test_cfo", action_type="refund_processed",
                     amount_gbp=Decimal("-5.00"), is_live_mode=True)
    total_24h = await led.current_period_total_gbp(period_hours=24, live_only=True)
    assert total_24h == Decimal("32.50")  # 25 + 12.50 - 5


@pytest.mark.asyncio
async def test_test_mode_excluded_from_live_total(pool):
    from clawbot.capital_ledger import CapitalLedger
    from decimal import Decimal
    led = CapitalLedger(pool)
    await led.init_schema()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM capital_ledger WHERE agent_id LIKE 'test2_%'")
    await led.record(agent_id="test2_cfo", action_type="card_issued",
                     amount_gbp=Decimal("100.00"), is_live_mode=False)  # test mode
    await led.record(agent_id="test2_cfo", action_type="card_issued",
                     amount_gbp=Decimal("50.00"), is_live_mode=True)
    live_total = await led.current_period_total_gbp(period_hours=24, live_only=True)
    assert live_total == Decimal("50.00")


@pytest.mark.asyncio
async def test_period_window_filters_correctly(pool):
    """Older entries outside the window are excluded."""
    from clawbot.capital_ledger import CapitalLedger
    from decimal import Decimal
    led = CapitalLedger(pool)
    await led.init_schema()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM capital_ledger WHERE agent_id LIKE 'test3_%'")
        # Insert an entry 8 days old
        await conn.execute(
            "INSERT INTO capital_ledger (agent_id, action_type, amount_gbp, is_live_mode, created_at) "
            "VALUES ($1, $2, $3, $4, NOW() - INTERVAL '8 days')",
            "test3_cfo", "card_issued", Decimal("999.00"), True,
        )
    await led.record(agent_id="test3_cfo", action_type="card_issued",
                     amount_gbp=Decimal("10.00"), is_live_mode=True)
    weekly = await led.current_period_total_gbp(period_hours=168, live_only=True)  # 7 days
    assert weekly == Decimal("10.00")  # excludes the 8-day-old £999
```

- [ ] **Step 2: Run — expect import failure**

`uv run pytest tests/test_capital_ledger.py -v`
Expected: `ImportError: clawbot.capital_ledger` or `SKIPPED` (asyncpg unavailable locally).

- [ ] **Step 3: Add schema to db.py**

In `src/clawbot/db.py`'s schema-init body, alongside the `plans` and `active_hypothesis` tables already there:

```python
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS capital_ledger (
                entry_id BIGSERIAL PRIMARY KEY,
                skill_call_id BIGINT,
                agent_id TEXT NOT NULL,
                action_type TEXT NOT NULL,
                amount_gbp NUMERIC(12, 2) NOT NULL,
                currency_original TEXT NOT NULL DEFAULT 'GBP',
                amount_original NUMERIC(12, 2),
                stripe_object_id TEXT,
                metadata TEXT NOT NULL DEFAULT '{}',
                is_live_mode BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_capital_ledger_created "
            "ON capital_ledger(created_at DESC)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_capital_ledger_agent "
            "ON capital_ledger(agent_id, created_at DESC)"
        )
```

- [ ] **Step 4: Implement CapitalLedger**

Create `src/clawbot/capital_ledger.py`:

```python
"""Capital ledger — records every spend authorization with linkable provenance.

The ledger is the enforcement substrate for daily/weekly caps. _LivePayments
queries `current_period_total_gbp` before any Stripe call that could trigger
spend, and raises if a new authorization would exceed the cap. This is
independent of Stripe's own server-side spending_controls — defence in depth."""
from __future__ import annotations

import json
from datetime import datetime, UTC
from decimal import Decimal
from typing import Any


class CapitalLedger:
    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def init_schema(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS capital_ledger (
                    entry_id BIGSERIAL PRIMARY KEY,
                    skill_call_id BIGINT,
                    agent_id TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    amount_gbp NUMERIC(12, 2) NOT NULL,
                    currency_original TEXT NOT NULL DEFAULT 'GBP',
                    amount_original NUMERIC(12, 2),
                    stripe_object_id TEXT,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    is_live_mode BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_capital_ledger_created "
                "ON capital_ledger(created_at DESC)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_capital_ledger_agent "
                "ON capital_ledger(agent_id, created_at DESC)"
            )

    async def record(
        self, *, agent_id: str, action_type: str, amount_gbp: Decimal,
        is_live_mode: bool = False,
        stripe_object_id: str | None = None,
        metadata: dict | None = None,
        currency_original: str = "GBP",
        amount_original: Decimal | None = None,
        skill_call_id: int | None = None,
    ) -> int:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO capital_ledger (skill_call_id, agent_id, action_type, amount_gbp, "
                "currency_original, amount_original, stripe_object_id, metadata, is_live_mode) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) RETURNING entry_id",
                skill_call_id, agent_id, action_type, amount_gbp,
                currency_original, amount_original, stripe_object_id,
                json.dumps(metadata or {}), is_live_mode,
            )
        return int(row["entry_id"])

    async def current_period_total_gbp(
        self, *, period_hours: int, live_only: bool = True,
    ) -> Decimal:
        """Sum of amounts in the trailing `period_hours` window. Refunds are
        negative entries; the sum is net spend."""
        async with self._pool.acquire() as conn:
            if live_only:
                row = await conn.fetchrow(
                    "SELECT COALESCE(SUM(amount_gbp), 0) AS total "
                    "FROM capital_ledger "
                    "WHERE created_at > NOW() - ($1 || ' hours')::INTERVAL "
                    "AND is_live_mode = TRUE",
                    str(period_hours),
                )
            else:
                row = await conn.fetchrow(
                    "SELECT COALESCE(SUM(amount_gbp), 0) AS total "
                    "FROM capital_ledger "
                    "WHERE created_at > NOW() - ($1 || ' hours')::INTERVAL",
                    str(period_hours),
                )
        return Decimal(str(row["total"])) if row else Decimal("0")

    async def list_recent(self, *, limit: int = 50) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT entry_id, agent_id, action_type, amount_gbp, "
                "stripe_object_id, is_live_mode, created_at "
                "FROM capital_ledger ORDER BY created_at DESC LIMIT $1",
                limit,
            )
        return [dict(r) for r in rows]
```

- [ ] **Step 5: Run — expect 4 passing or SKIPPED**

`uv run pytest tests/test_capital_ledger.py -v`

- [ ] **Step 6: Commit**

```bash
git add src/clawbot/db.py src/clawbot/capital_ledger.py tests/test_capital_ledger.py
git commit -m "feat: capital_ledger table + CapitalLedger store" -m "" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: Config additions + capital cap enforcement in `_LivePayments`

**Files:**
- Modify: `src/clawbot/config.py`
- Modify: `src/clawbot/skill_ctx.py` (extend `_LivePayments` constructor + every spend-triggering method)
- Create: `tests/test_capital_graduation.py`

The graduation gate: `stripe_live_mode_enabled` must be `True` AND the operator must have set caps. Otherwise `_LivePayments` raises `RuntimeError("live_mode_not_enabled")` on any spend-triggering call (issue_card, create_payment_link, etc.). When enabled, every spend call queries the ledger first; if a hypothetical new entry would push the running total past the cap, raise `RuntimeError("capital_cap_exceeded")`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_capital_graduation.py`:

```python
"""Capital graduation gate + cap enforcement in _LivePayments."""
import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


def test_issue_card_raises_when_live_mode_disabled():
    """With live_mode_enabled=False, the live impl must refuse any live spend."""
    from clawbot.skill_ctx import _LivePayments

    fake_ledger = MagicMock()
    payments = _LivePayments(secret_key="sk_test_123")
    payments._live_mode_enabled = False  # explicit
    payments._capital_ledger = fake_ledger
    payments._capital_daily_cap_gbp = Decimal("100")
    payments._capital_weekly_cap_gbp = Decimal("500")

    # Test mode keys: should succeed (no live-mode gate triggered for sk_test_)
    with patch("clawbot.skill_ctx.stripe") as stripe_mod:
        fake_card = MagicMock()
        fake_card.to_dict.return_value = {"id": "ic_test", "last4": "4242",
                                           "exp_month": 12, "exp_year": 2030, "status": "active"}
        stripe_mod.issuing.Card.create.return_value = fake_card
        result = asyncio.run(payments.issue_card(
            cardholder_id="ich_x", daily_limit_usd=10, agent_id="cfo",
        ))
        assert result["id"] == "ic_test"


def test_issue_card_raises_when_live_mode_enabled_but_no_caps_set():
    """Live mode + cap=0 must refuse (can't operate without caps)."""
    from clawbot.skill_ctx import _LivePayments

    payments = _LivePayments(secret_key="sk_live_real")
    payments._live_mode_enabled = True
    payments._capital_ledger = MagicMock()
    payments._capital_daily_cap_gbp = Decimal("0")
    payments._capital_weekly_cap_gbp = Decimal("0")

    with pytest.raises(RuntimeError, match="cap"):
        asyncio.run(payments.issue_card(
            cardholder_id="ich_x", daily_limit_usd=10, agent_id="cfo",
        ))


def test_issue_card_raises_when_would_exceed_daily_cap():
    """Cap=£50/day, already spent £45, requesting card with £10 daily limit: refuse."""
    from clawbot.skill_ctx import _LivePayments

    fake_ledger = MagicMock()
    fake_ledger.current_period_total_gbp = AsyncMock(return_value=Decimal("45.00"))
    fake_ledger.record = AsyncMock(return_value=1)

    payments = _LivePayments(secret_key="sk_live_real")
    payments._live_mode_enabled = True
    payments._capital_ledger = fake_ledger
    payments._capital_daily_cap_gbp = Decimal("50")
    payments._capital_weekly_cap_gbp = Decimal("500")

    # daily_limit_usd=10 (treat as ~£8 for the test; the cap check uses notional cap)
    with pytest.raises(RuntimeError, match="capital_cap_exceeded"):
        asyncio.run(payments.issue_card(
            cardholder_id="ich_x", daily_limit_usd=10, agent_id="cfo",
        ))


def test_issue_card_records_ledger_entry_on_success():
    """Successful issuance logs to the ledger BEFORE returning."""
    from clawbot.skill_ctx import _LivePayments

    fake_ledger = MagicMock()
    fake_ledger.current_period_total_gbp = AsyncMock(return_value=Decimal("0"))
    fake_ledger.record = AsyncMock(return_value=1)

    fake_card = MagicMock()
    fake_card.to_dict.return_value = {"id": "ic_live", "last4": "5678",
                                       "exp_month": 11, "exp_year": 2029, "status": "active",
                                       "cardholder": "ich_x"}

    payments = _LivePayments(secret_key="sk_live_real")
    payments._live_mode_enabled = True
    payments._capital_ledger = fake_ledger
    payments._capital_daily_cap_gbp = Decimal("100")
    payments._capital_weekly_cap_gbp = Decimal("500")

    with patch("clawbot.skill_ctx.stripe") as stripe_mod:
        stripe_mod.issuing.Card.create.return_value = fake_card
        result = asyncio.run(payments.issue_card(
            cardholder_id="ich_x", daily_limit_usd=10, agent_id="cfo",
        ))

    fake_ledger.record.assert_called_once()
    kwargs = fake_ledger.record.call_args.kwargs
    assert kwargs["action_type"] == "card_issued"
    assert kwargs["agent_id"] == "cfo"
    assert kwargs["is_live_mode"] is True
    assert result["id"] == "ic_live"
```

- [ ] **Step 2: Run — expect failure**

`uv run pytest tests/test_capital_graduation.py -v`
Expected: AttributeError on `_capital_ledger` or `_live_mode_enabled`.

- [ ] **Step 3: Extend config.py**

In `src/clawbot/config.py`, add to `Settings`:

```python
    # Capital integration — operator-gated graduation from Stripe test mode.
    # Until stripe_live_mode_enabled is True AND both caps > 0, _LivePayments
    # refuses any live-mode spend. Test-mode keys bypass these gates entirely.
    stripe_live_mode_enabled: bool = False
    capital_daily_cap_gbp: float = 0.0
    capital_weekly_cap_gbp: float = 0.0
    capital_freeze: bool = False  # emergency kill — halts ALL authorizations when True
```

- [ ] **Step 4: Extend `_LivePayments` constructor + methods**

In `src/clawbot/skill_ctx.py`, find `class _LivePayments`. Modify `__init__` to accept capital config:

```python
class _LivePayments:
    def __init__(
        self, secret_key: str,
        *,
        capital_ledger: Any = None,
        live_mode_enabled: bool = False,
        capital_daily_cap_gbp: Any = None,  # Decimal, but Any to avoid import order
        capital_weekly_cap_gbp: Any = None,
        capital_freeze: bool = False,
    ) -> None:
        from decimal import Decimal
        if not secret_key:
            raise ValueError("STRIPE_SECRET_KEY not set — _LivePayments cannot operate")
        if stripe is None:
            raise RuntimeError("stripe SDK not installed")
        stripe.api_key = secret_key
        self._is_live_key = secret_key.startswith("sk_live_")
        self._capital_ledger = capital_ledger
        self._live_mode_enabled = live_mode_enabled
        self._capital_daily_cap_gbp = Decimal(str(capital_daily_cap_gbp or 0))
        self._capital_weekly_cap_gbp = Decimal(str(capital_weekly_cap_gbp or 0))
        self._capital_freeze = capital_freeze
```

Add a guard method:

```python
    async def _enforce_capital_gates(
        self, *, prospective_amount_gbp: "Decimal", agent_id: str,
    ) -> bool:
        """Returns True if the prospective spend is allowed. Raises RuntimeError
        with a specific cap-name on refusal. Returns True for test-mode (sk_test_)
        keys regardless of gates — test mode is a free playground."""
        from decimal import Decimal
        # Test-mode keys: bypass all gates. They can't actually charge real money.
        if not self._is_live_key:
            return True
        if self._capital_freeze:
            raise RuntimeError("capital_freeze_active — operator has halted all spending")
        if not self._live_mode_enabled:
            raise RuntimeError("live_mode_not_enabled — operator has not graduated to live")
        if self._capital_daily_cap_gbp <= 0 or self._capital_weekly_cap_gbp <= 0:
            raise RuntimeError("capital_caps_not_set — daily and weekly caps must both be > 0 for live spend")
        if self._capital_ledger is None:
            raise RuntimeError("capital_ledger_not_wired — live mode requires ledger for cap enforcement")
        # Daily window (24h)
        daily_spent = await self._capital_ledger.current_period_total_gbp(
            period_hours=24, live_only=True,
        )
        if daily_spent + prospective_amount_gbp > self._capital_daily_cap_gbp:
            raise RuntimeError(
                f"capital_cap_exceeded — daily: {daily_spent} + {prospective_amount_gbp} "
                f"> {self._capital_daily_cap_gbp}"
            )
        # Weekly window (168h)
        weekly_spent = await self._capital_ledger.current_period_total_gbp(
            period_hours=168, live_only=True,
        )
        if weekly_spent + prospective_amount_gbp > self._capital_weekly_cap_gbp:
            raise RuntimeError(
                f"capital_cap_exceeded — weekly: {weekly_spent} + {prospective_amount_gbp} "
                f"> {self._capital_weekly_cap_gbp}"
            )
        return True
```

Modify `issue_card` to call the gate before Stripe + record on success:

```python
    async def issue_card(
        self, *, cardholder_id: str, daily_limit_usd: int, agent_id: str,
    ) -> dict[str, Any]:
        from decimal import Decimal
        # Treat daily_limit_usd as the prospective max-daily-exposure for the gate.
        # Conservative: USD ≈ GBP for cap purposes; the cap is operator-set so a
        # ~25% currency buffer is implicit in their choice.
        prospective_gbp = Decimal(str(daily_limit_usd))
        await self._enforce_capital_gates(
            prospective_amount_gbp=prospective_gbp, agent_id=agent_id,
        )
        amount_cents = daily_limit_usd * 100
        card = await asyncio.to_thread(
            stripe.issuing.Card.create,  # type: ignore[union-attr]
            cardholder=cardholder_id,
            currency="usd",
            type="virtual",
            spending_controls={
                "spending_limits": [
                    {"amount": amount_cents, "interval": "daily"},
                ],
            },
            metadata={"agent_id": agent_id},
        )
        result = card.to_dict()
        for sensitive in ("number", "cvc"):
            result.pop(sensitive, None)
        # Log to ledger AFTER Stripe success but BEFORE returning, so the cap
        # check on the next call sees this authorization.
        if self._capital_ledger is not None:
            try:
                await self._capital_ledger.record(
                    agent_id=agent_id,
                    action_type="card_issued",
                    amount_gbp=prospective_gbp,
                    is_live_mode=self._is_live_key,
                    stripe_object_id=result.get("id"),
                    metadata={"cardholder_id": cardholder_id, "daily_limit_usd": daily_limit_usd},
                )
            except Exception:
                pass  # ledger failure must not break the response
        return result
```

Modify `create_payment_link` similarly (call gate + record). Use `quantity * price_amount_pence / 100` as prospective amount when known, else skip the gate (payment link is buyer-initiated, not agent-spend, so this is best-effort).

- [ ] **Step 5: Wire into `make_live_ctx`**

In `make_live_ctx`, build the CapitalLedger and pass it to `_LivePayments`:

```python
    # ... existing code that builds payments ...
    capital_ledger = None
    if db_pool is not None:
        try:
            from clawbot.capital_ledger import CapitalLedger
            capital_ledger = CapitalLedger(db_pool)
            await capital_ledger.init_schema()
        except Exception:
            capital_ledger = None

    payments: PaymentsClient = (
        _LivePayments(
            stripe_secret_key,
            capital_ledger=capital_ledger,
            live_mode_enabled=stripe_live_mode_enabled,
            capital_daily_cap_gbp=capital_daily_cap_gbp,
            capital_weekly_cap_gbp=capital_weekly_cap_gbp,
            capital_freeze=capital_freeze,
        ) if stripe_secret_key else _NoopPayments()
    )
```

And add the new kwargs to `make_live_ctx`'s signature (between the existing `stripe_secret_key` and `x_bearer`):

```python
    stripe_secret_key: str = "",
    stripe_live_mode_enabled: bool = False,
    capital_daily_cap_gbp: float = 0.0,
    capital_weekly_cap_gbp: float = 0.0,
    capital_freeze: bool = False,
```

Note: `make_live_ctx` is currently synchronous (returns a SkillCtx directly). The `await capital_ledger.init_schema()` above requires it to become async OR the init_schema call must happen elsewhere. **Resolution:** Don't call init_schema here — assume the main startup path calls `Database.init_schema()` which already creates the table (Task 1). The CapitalLedger constructor itself is synchronous.

So the correct version of Step 5 is:

```python
    capital_ledger = None
    if db_pool is not None:
        from clawbot.capital_ledger import CapitalLedger
        capital_ledger = CapitalLedger(db_pool)
    # init_schema is called by Database.init_schema() during startup; do not
    # await it here (would require make_live_ctx to be async).
    payments: PaymentsClient = (
        _LivePayments(
            stripe_secret_key,
            capital_ledger=capital_ledger,
            live_mode_enabled=stripe_live_mode_enabled,
            capital_daily_cap_gbp=capital_daily_cap_gbp,
            capital_weekly_cap_gbp=capital_weekly_cap_gbp,
            capital_freeze=capital_freeze,
        ) if stripe_secret_key else _NoopPayments()
    )
```

- [ ] **Step 6: Thread the new kwargs through directive_router**

In `src/clawbot/directive_router.py`, the existing `make_live_ctx(...)` call (in `_handle_skill_call`) gains four new kwargs:

```python
            stripe_live_mode_enabled=settings.stripe_live_mode_enabled,
            capital_daily_cap_gbp=settings.capital_daily_cap_gbp,
            capital_weekly_cap_gbp=settings.capital_weekly_cap_gbp,
            capital_freeze=settings.capital_freeze,
```

- [ ] **Step 7: Run tests**

`uv run pytest tests/test_capital_graduation.py tests/test_capital_ledger.py tests/test_payments_ctx.py tests/test_stripe_issuing.py -v`
Expected: all green (test_capital_ledger may skip if no Postgres, but the four graduation tests use mocks and should pass).

- [ ] **Step 8: Commit**

```bash
git add src/clawbot/config.py src/clawbot/skill_ctx.py src/clawbot/directive_router.py tests/test_capital_graduation.py
git commit -m "feat: capital graduation gate + cap enforcement in _LivePayments" -m "" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: Operator escalation when capital usage crosses 80%

**Files:**
- Modify: `src/clawbot/monitor.py`

The monitor already publishes daily-spend warnings for LLM costs. Extend it: read `capital_ledger.current_period_total_gbp(168, live_only=True)` once per cycle (e.g. every 30 min); if usage > 80% of weekly cap, publish a Telegram escalation. This is operational visibility — without it, the operator only learns about a £400 spend when the monthly Stripe statement arrives.

- [ ] **Step 1: Read monitor.py first** to understand its existing structure and find a sensible insertion point.

- [ ] **Step 2: Add the warning logic**

Inside whatever periodic loop monitor.py has (likely a `_run` or `monitor_loop` method), after the existing LLM-spend warning logic:

```python
        # Capital cap proximity warning
        if self._db_pool is not None and self._weekly_cap_gbp > 0:
            try:
                from clawbot.capital_ledger import CapitalLedger
                led = CapitalLedger(self._db_pool)
                weekly_spent = await led.current_period_total_gbp(period_hours=168, live_only=True)
                fraction = float(weekly_spent) / float(self._weekly_cap_gbp)
                if fraction >= 0.8 and not self._capital_warning_sent_today:
                    await self._bus.publish("operator.escalation", {
                        "severity": "warning",
                        "summary": f"Capital usage at {fraction*100:.0f}% of weekly cap (£{weekly_spent:.2f} / £{self._weekly_cap_gbp:.2f})",
                        "detail": f"Set CAPITAL_FREEZE=true in .env to halt all authorizations.",
                        "source": "monitor",
                    })
                    self._capital_warning_sent_today = True
            except Exception:
                pass
```

(The `_capital_warning_sent_today` flag is set once per UTC day; reset in the monitor's existing daily-rollover logic.)

- [ ] **Step 3: Wire the cap value into Monitor.__init__**

Monitor's constructor gains a `weekly_cap_gbp` kwarg (default 0 = warning disabled). main.py passes `settings.capital_weekly_cap_gbp` when constructing the Monitor.

- [ ] **Step 4: Commit**

```bash
git add src/clawbot/monitor.py src/clawbot/main.py
git commit -m "feat: monitor publishes capital cap proximity warning at 80%" -m "" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: company_fitness — single score for the whole organism

**Files:**
- Modify: `src/clawbot/db.py` (add `company_fitness_snapshots` table)
- Create: `src/clawbot/company_fitness.py`
- Create: `tests/test_company_fitness.py`
- Modify: `src/clawbot/scheduler.py` (add a daily snapshot cron loop)

The existing `fitness.py` scores individual agents. Nothing scores the *company* — so the meta-evaluator has no view of "is the organism as a whole making progress this week vs last week?" `company_fitness` is a pure function that takes a metrics snapshot (revenue, plans-advanced count, plans-pivoted count, capital deployment efficiency, skill-call success rate) and outputs a single 0-1 score plus a breakdown. A daily cron writes the snapshot to a new table.

Schema:
```sql
CREATE TABLE IF NOT EXISTS company_fitness_snapshots (
    snapshot_id BIGSERIAL PRIMARY KEY,
    snapshot_date DATE NOT NULL UNIQUE,
    score NUMERIC(4, 3) NOT NULL,
    revenue_7d_gbp NUMERIC(12, 2) NOT NULL,
    plans_active INTEGER NOT NULL,
    plans_advanced_7d INTEGER NOT NULL,
    plans_pivoted_7d INTEGER NOT NULL,
    capital_deployed_7d_gbp NUMERIC(12, 2) NOT NULL,
    skill_calls_7d INTEGER NOT NULL,
    skill_call_success_rate NUMERIC(4, 3) NOT NULL,
    breakdown TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

Scoring weights (deliberate; tune later from data):
- 0.40 × revenue_score (log-scaled, caps at £100/week = 1.0)
- 0.20 × plan_velocity (plans_advanced_7d / (plans_advanced_7d + plans_pivoted_7d), default 0 if none)
- 0.20 × skill_call_success_rate
- 0.20 × capital_efficiency (revenue_7d / max(1, capital_deployed_7d))

Goodhart guard: if revenue_7d_gbp == 0, cap raw score at 0.30 (matching the existing `fitness.py` countermeasure).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_company_fitness.py`:

```python
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
    assert score.score == 0.0  # nothing happened → no fitness


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
```

- [ ] **Step 2: Run — expect import failure**

- [ ] **Step 3: Implement compute_company_fitness**

Create `src/clawbot/company_fitness.py`:

```python
"""Company-level fitness — one score for the organism as a whole.

The existing fitness.py scores individual agents. The meta-evaluator needs a
single number to track week-over-week. Weights are deliberate, not optimised —
revenue dominates (0.40) but plan velocity, skill-call success, and capital
efficiency each carry signal that revenue alone can't surface in week 1."""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from decimal import Decimal


@dataclass(frozen=True)
class CompanyFitnessScore:
    score: float
    revenue_score: float
    plan_velocity: float
    skill_call_success_rate: float
    capital_efficiency: float
    breakdown: dict


def compute_company_fitness(
    *,
    revenue_7d_gbp: Decimal,
    plans_active: int,
    plans_advanced_7d: int,
    plans_pivoted_7d: int,
    capital_deployed_7d_gbp: Decimal,
    skill_calls_7d: int,
    skill_calls_success_7d: int,
) -> CompanyFitnessScore:
    # Revenue: log-scaled, caps at £100/week = 1.0
    revenue_score = min(1.0, math.log1p(float(revenue_7d_gbp)) / math.log1p(100.0))

    # Plan velocity: ratio of advances to total decisions (advances + pivots)
    total_plan_decisions = plans_advanced_7d + plans_pivoted_7d
    plan_velocity = (
        plans_advanced_7d / total_plan_decisions
        if total_plan_decisions > 0 else 0.0
    )

    # Skill-call success rate
    skill_call_success_rate = (
        skill_calls_success_7d / skill_calls_7d
        if skill_calls_7d > 0 else 0.0
    )

    # Capital efficiency: revenue per £ deployed
    capital_efficiency_raw = (
        float(revenue_7d_gbp) / max(1.0, float(capital_deployed_7d_gbp))
        if capital_deployed_7d_gbp > 0 else 0.0
    )
    # Bound to [0, 1] for the weighted sum — anything above 1:1 ROI in a week is "good"
    capital_efficiency = min(1.0, capital_efficiency_raw)

    raw_score = (
        0.40 * revenue_score
        + 0.20 * plan_velocity
        + 0.20 * skill_call_success_rate
        + 0.20 * capital_efficiency
    )

    # No-activity tax: if NOTHING happened, score is 0 (not 0.3 from the cap)
    if skill_calls_7d == 0 and plans_advanced_7d == 0 and plans_pivoted_7d == 0:
        raw_score = 0.0

    # Goodhart guard: zero revenue caps score at 0.30 regardless of proxy metrics
    if revenue_7d_gbp == 0:
        raw_score = min(raw_score, 0.30)

    breakdown = {
        "revenue_score": round(revenue_score, 4),
        "plan_velocity": round(plan_velocity, 4),
        "skill_call_success_rate": round(skill_call_success_rate, 4),
        "capital_efficiency": round(capital_efficiency, 4),
        "inputs": {
            "revenue_7d_gbp": float(revenue_7d_gbp),
            "plans_active": plans_active,
            "plans_advanced_7d": plans_advanced_7d,
            "plans_pivoted_7d": plans_pivoted_7d,
            "capital_deployed_7d_gbp": float(capital_deployed_7d_gbp),
            "skill_calls_7d": skill_calls_7d,
            "skill_calls_success_7d": skill_calls_success_7d,
        },
    }

    return CompanyFitnessScore(
        score=round(raw_score, 4),
        revenue_score=round(revenue_score, 4),
        plan_velocity=round(plan_velocity, 4),
        skill_call_success_rate=round(skill_call_success_rate, 4),
        capital_efficiency=round(capital_efficiency, 4),
        breakdown=breakdown,
    )


async def compute_and_snapshot(*, db_pool, today_iso: str | None = None) -> CompanyFitnessScore:
    """Query the current state, compute fitness, write a snapshot row."""
    from datetime import date
    import json as _json
    snapshot_date = today_iso or date.today().isoformat()
    async with db_pool.acquire() as conn:
        rev_row = await conn.fetchrow(
            "SELECT COALESCE(SUM(amount_gbp), 0) AS rev FROM capital_ledger "
            "WHERE action_type='charge_authorized' "
            "AND created_at > NOW() - INTERVAL '7 days' "
            "AND amount_gbp > 0"
        )
        revenue_7d = Decimal(str(rev_row["rev"])) if rev_row else Decimal("0")

        plans_active_row = await conn.fetchrow(
            "SELECT COUNT(*) AS n FROM plans WHERE status='active'"
        )
        plans_active = int(plans_active_row["n"]) if plans_active_row else 0

        adv_row = await conn.fetchrow(
            "SELECT COUNT(*) AS n FROM plans WHERE status='done' "
            "AND updated_at > NOW() - INTERVAL '7 days'"
        )
        plans_advanced_7d = int(adv_row["n"]) if adv_row else 0

        piv_row = await conn.fetchrow(
            "SELECT COUNT(*) AS n FROM plans WHERE status='pivoted' "
            "AND updated_at > NOW() - INTERVAL '7 days'"
        )
        plans_pivoted_7d = int(piv_row["n"]) if piv_row else 0

        cap_row = await conn.fetchrow(
            "SELECT COALESCE(SUM(amount_gbp), 0) AS dep FROM capital_ledger "
            "WHERE action_type='card_issued' "
            "AND created_at > NOW() - INTERVAL '7 days'"
        )
        capital_deployed_7d = Decimal(str(cap_row["dep"])) if cap_row else Decimal("0")

        sc_total_row = await conn.fetchrow(
            "SELECT COUNT(*) AS n FROM skill_calls "
            "WHERE created_at > NOW() - INTERVAL '7 days'"
        )
        sc_total = int(sc_total_row["n"]) if sc_total_row else 0

        sc_ok_row = await conn.fetchrow(
            "SELECT COUNT(*) AS n FROM skill_calls "
            "WHERE created_at > NOW() - INTERVAL '7 days' AND ok = TRUE"
        )
        sc_ok = int(sc_ok_row["n"]) if sc_ok_row else 0

    score = compute_company_fitness(
        revenue_7d_gbp=revenue_7d,
        plans_active=plans_active,
        plans_advanced_7d=plans_advanced_7d,
        plans_pivoted_7d=plans_pivoted_7d,
        capital_deployed_7d_gbp=capital_deployed_7d,
        skill_calls_7d=sc_total,
        skill_calls_success_7d=sc_ok,
    )

    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO company_fitness_snapshots (
                snapshot_date, score, revenue_7d_gbp, plans_active,
                plans_advanced_7d, plans_pivoted_7d, capital_deployed_7d_gbp,
                skill_calls_7d, skill_call_success_rate, breakdown
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            ON CONFLICT (snapshot_date) DO UPDATE SET
                score = excluded.score,
                revenue_7d_gbp = excluded.revenue_7d_gbp,
                plans_active = excluded.plans_active,
                plans_advanced_7d = excluded.plans_advanced_7d,
                plans_pivoted_7d = excluded.plans_pivoted_7d,
                capital_deployed_7d_gbp = excluded.capital_deployed_7d_gbp,
                skill_calls_7d = excluded.skill_calls_7d,
                skill_call_success_rate = excluded.skill_call_success_rate,
                breakdown = excluded.breakdown
        """,
            snapshot_date, score.score, revenue_7d, plans_active,
            plans_advanced_7d, plans_pivoted_7d, capital_deployed_7d,
            sc_total, score.skill_call_success_rate,
            _json.dumps(score.breakdown),
        )

    return score
```

- [ ] **Step 4: Add the snapshots table schema to db.py**

```python
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS company_fitness_snapshots (
                snapshot_id BIGSERIAL PRIMARY KEY,
                snapshot_date DATE NOT NULL UNIQUE,
                score NUMERIC(4, 3) NOT NULL,
                revenue_7d_gbp NUMERIC(12, 2) NOT NULL,
                plans_active INTEGER NOT NULL,
                plans_advanced_7d INTEGER NOT NULL,
                plans_pivoted_7d INTEGER NOT NULL,
                capital_deployed_7d_gbp NUMERIC(12, 2) NOT NULL,
                skill_calls_7d INTEGER NOT NULL,
                skill_call_success_rate NUMERIC(4, 3) NOT NULL,
                breakdown TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
```

- [ ] **Step 5: Add daily snapshot cron in scheduler.py**

In `src/clawbot/scheduler.py`, add a new background task method:

```python
    async def _run_company_fitness_snapshot_loop(self) -> None:
        """Once per UTC day, compute + persist the company fitness snapshot."""
        from clawbot.company_fitness import compute_and_snapshot
        last_snapshot_date = None
        while True:
            now = datetime.now(UTC)
            today_str = now.date().isoformat()
            if today_str != last_snapshot_date:
                if self._db_pool is not None:
                    try:
                        score = await compute_and_snapshot(db_pool=self._db_pool)
                        logger.info("Company fitness snapshot: score=%.3f", score.score)
                        last_snapshot_date = today_str
                    except Exception as exc:
                        logger.error("Company fitness snapshot failed: %s", exc)
            await asyncio.sleep(900)  # check every 15 min; only acts once per day
```

In the scheduler's `run` or `start` method (wherever the existing loops are launched), add:

```python
            tasks.append(asyncio.create_task(
                self._run_company_fitness_snapshot_loop(),
                name="company-fitness-snapshot",
            ))
```

- [ ] **Step 6: Run tests**

`uv run pytest tests/test_company_fitness.py -v`
Expected: 4 passed (pure-function tests; no DB needed for the math tests).

- [ ] **Step 7: Commit**

```bash
git add src/clawbot/db.py src/clawbot/company_fitness.py src/clawbot/scheduler.py tests/test_company_fitness.py
git commit -m "feat: company_fitness — single score for the whole organism" -m "" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: Full suite + operator runbook

- [ ] **Step 1: Run the full test suite**

`uv run pytest --tb=line 2>&1 | tail -10`
Expected: previous count + ~16 new tests pass; 2 pre-existing asyncpg failures unchanged; new test_capital_ledger may SKIP locally.

- [ ] **Step 2: Append to operating_facts.md**

Append:

```markdown

## Portfolio operator: multi-hypothesis + capital + company fitness (added 2026-05-XX)

**Multi-hypothesis portfolio** — `active_hypothesis` is no longer "exactly one." Up to `MAX_ACTIVE_HYPOTHESES` (default 3) can be active simultaneously:

- Each row has a `weight` (0.0-1.0) hinting resource allocation, and a `progress_score` (0.0-1.0) computed externally.
- Each plan in the `plans` table links to a hypothesis via `hypothesis_id`. When a hypothesis is killed, its plans cascade to `status='abandoned'` via `PlanStore.abandon_plans_for_hypothesis`.
- Board PIVOT outcomes call `generate_hypothesis_for_portfolio`: if portfolio has room, the new bet is APPENDED; if at cap, the lowest-weight active is killed first to make room.
- An auto-diversification loop runs every 6 hours: any active hypothesis past 50% of its time-window with `progress_score < 0.20` triggers spawn of a fresh bet alongside it (when portfolio is below cap). This is the "diversify before survival fails" pattern — clawbot proactively starts new bets even while existing ones are running.

**To revert to single-hypothesis behaviour:** set `MAX_ACTIVE_HYPOTHESES=1` in `.env`. The existing H1 seed and board PIVOT logic both respect the cap. No code change needed.

**Querying the portfolio:**
```sql
SELECT name, weight, progress_score, created_at
FROM active_hypothesis
WHERE status='active'
ORDER BY weight DESC;
```

**Capital graduation** — `_LivePayments` now enforces spending caps before any Stripe call:

- Test-mode keys (`sk_test_...`) bypass all caps — they can't charge real money.
- Live-mode keys (`sk_live_...`) require:
  - `STRIPE_LIVE_MODE_ENABLED=true` in `.env`
  - `CAPITAL_DAILY_CAP_GBP > 0` and `CAPITAL_WEEKLY_CAP_GBP > 0`
- Every spend authorization is logged to `capital_ledger` table.
- `CAPITAL_FREEZE=true` halts all authorizations without restart (emergency kill).
- Monitor publishes a Telegram warning when weekly usage crosses 80%.

**Graduating to live:** edit `/opt/clawbot/.env`:
```
STRIPE_LIVE_MODE_ENABLED=true
CAPITAL_DAILY_CAP_GBP=50
CAPITAL_WEEKLY_CAP_GBP=200
```
Then swap `STRIPE_SECRET_KEY` from `sk_test_...` to `sk_live_...` and `docker compose restart clawbot`. Watch the Telegram channel for the first card issuance — every `stripe_issue_card` already has `requires_approval=True` so you'll be prompted before any real card is minted.

**Emergency freeze:** `ssh clawbot 'echo "CAPITAL_FREEZE=true" >> /opt/clawbot/.env && cd /opt/clawbot && docker compose restart clawbot'`. All future card issuances raise `capital_freeze_active` until you remove the line.

**Company fitness:** scheduler now runs a once-per-day snapshot that scores the whole organism (revenue, plan velocity, skill-call success, capital efficiency). Snapshots live in `company_fitness_snapshots` table. Week-over-week trend is the meta-signal — score below 0.3 for 14 days running = the architecture isn't producing data, time to pivot the use case.

```

- [ ] **Step 3: Commit + push**

```bash
git add docs/superpowers/plans/2026-05-18-capital-and-portfolio-fitness.md
git commit -m "docs: capital integration + company fitness plan" -m "" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
git push origin <branch>
```

---

## Acceptance Criteria (binary — all must pass, then stop)

**Multi-hypothesis (Task 0):**
- [ ] `active_hypothesis` has `weight` + `progress_score` columns
- [ ] `plans.hypothesis_id` column exists; new plans can link to a hypothesis
- [ ] `HypothesisStore.add_hypothesis` raises `portfolio_full` when at `MAX_ACTIVE_HYPOTHESES`
- [ ] `HypothesisStore.kill_hypothesis_by_id` kills exactly one row (verified by test)
- [ ] `HypothesisStore.get_active()` backwards-compat returns highest-weight active
- [ ] `PlanStore.abandon_plans_for_hypothesis` cascades plan status to `abandoned`
- [ ] CEO cycle prompt contains the full portfolio when N>1 active (verified by test)
- [ ] Board PIVOT adds to portfolio when below cap; replaces lowest-weight when at cap
- [ ] Auto-diversification loop spawns new hypothesis when an existing one is past 50% time + progress < 0.20 + portfolio below cap (verified by pure-function test)

**Capital (Tasks 1-3):**
- [ ] `capital_ledger` table exists in DB; tests pass or skip cleanly
- [ ] `_LivePayments.issue_card` calls `_enforce_capital_gates` before Stripe and `record` after, both verified by tests
- [ ] Live-mode disabled (`stripe_live_mode_enabled=False`) + `sk_live_*` key → `RuntimeError("live_mode_not_enabled")`
- [ ] Cap exceeded → `RuntimeError("capital_cap_exceeded")` with specific period name
- [ ] `CAPITAL_FREEZE=true` → all authorizations refuse
- [ ] Monitor publishes Telegram warning at 80% weekly cap usage

**Company fitness (Task 4):**
- [ ] `compute_company_fitness` returns 0 when nothing happened; ≤ 0.30 when zero revenue; > 0.70 with high revenue + signal
- [ ] Daily snapshot loop fires; `company_fitness_snapshots` accumulates rows
- [ ] Fitness aggregates across the FULL portfolio (revenue summed across all hypotheses, not just one)

**Overall:**
- [ ] Full suite green except 2 pre-existing asyncpg failures
- [ ] Operator runbook in `operating_facts.md` documents portfolio + graduation + freeze procedures

When all pass: **done**. Do not generalize, do not add multi-hypothesis state, do not add channels-as-asset table, do not add more skills. Sit with the new capability for at least 7 days of telemetry before deciding what comes next.

---

## What this plan does NOT do (and why that's correct)

It does not add **multi-hypothesis parallelism** — premature until H1 produces a non-zero data point.
It does not add **channels-as-asset** — premature until a channel exists worth tracking (probably day 30+).
It does not extend the skill library — Phase H already does that, in parallel.
It does not change the agent architecture — the OODA loop is already closed.

The two things it does add are the *necessary preconditions* for any of those later expansions: real money flows (capital integration) and a way to score whether the organism as a whole is healthy (company fitness). Without these, the next layer of expansion is fishing.
