# Causal Attribution Living System — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform clawbot from a deliberation system that produces bus messages nobody reads into a living system that executes directives, traces market-signal → action → sale causality, and evolves on per-agent attributed revenue rather than a shared equal-split proxy.

**Architecture:** A Causal Attribution Graph (CAG) is installed first — before any execution kernel — because fitness evolution without attribution collapses to Goodhart's Law (Gumroad bus activity proxy replaces actual revenue). Every executive directive carries a `chain_id`; the DirectiveRouter records each action as a chain event at increasing depth; when a Gumroad sale occurs against a mapped product, `close_chain()` distributes revenue inversely by depth. Only after attribution is operational do self-scheduling, agent inboxes, web research, and the lateral thinker layers activate.

**Tech Stack:** asyncpg (pgvector already present), Redis Streams, asyncio, pytest-asyncio, httpx

---

## File Map

| File | Change |
|---|---|
| `src/clawbot/db.py` | Add `causal_chain` + `product_causal_map` tables to `init_schema()` |
| `src/clawbot/causal_store.py` | **CREATE** — CausalStore class, full attribution logic |
| `src/clawbot/opportunity_scanner.py` | Generate `chain_id` per opportunity; record depth-0 event |
| `src/clawbot/fitness.py` | Add `attributed_revenue_7d_gbp` + `attribution_rate` fields to FitnessScore |
| `src/clawbot/fitness_writer.py` | Accept `causal_store` param; use attributed revenue if available |
| `src/clawbot/json_util.py` | **CREATE** — extract `_extract_json` from scheduler |
| `src/clawbot/directive_router.py` | **CREATE** — DirectiveRouter with at-least-once delivery + CAG recording |
| `src/clawbot/task_store.py` | **CREATE** — JSONL task queue with per-agent read/complete/fail |
| `src/clawbot/lateral_thinker.py` | **CREATE** — weekly cross-signal synthesis with freshness gate |
| `src/clawbot/scheduler.py` | Add chain_id to directives; wire DirectiveRouter + TaskStore + LateralThinker + self-scheduling + inboxes |
| `src/clawbot/main.py` | Pass `causal_store` + `task_store` to Scheduler; subscribe new topics |
| `tests/test_causal_store.py` | **CREATE** |
| `tests/test_directive_router.py` | **CREATE** |
| `tests/test_task_store.py` | **CREATE** |
| `tests/test_lateral_thinker.py` | **CREATE** |
| `tests/test_fitness.py` | Extend existing |
| `tests/test_fitness_writer.py` | Extend existing |
| `tests/test_scheduler_selfschedule.py` | **CREATE** |

---

## Phase 0 — Causal Attribution Graph Infrastructure

**Sequencing rationale:** Attribution infrastructure must exist before the execution kernel fires a single action. Installing DirectiveRouter on a flat equal-share fitness function causes evolution to optimise for bus-visible busyness (Goodhart), not revenue. Attribution first, execution second.

### Task 0.1: CAG Database Schema

**Files:**
- Modify: `src/clawbot/db.py:44-67`
- Test: `tests/test_causal_store.py` (schema test, mock pool)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_causal_store.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_pool():
    pool = MagicMock()
    pool.execute = AsyncMock()
    pool.fetch = AsyncMock(return_value=[])
    pool.fetchval = AsyncMock(return_value=None)
    pool.acquire = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=pool)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
    pool.transaction = MagicMock()
    pool.transaction.return_value.__aenter__ = AsyncMock(return_value=None)
    pool.transaction.return_value.__aexit__ = AsyncMock(return_value=None)
    return pool


async def test_db_init_schema_creates_causal_chain_table():
    from clawbot.db import Database
    db = Database("postgresql://test/test")
    db._pool = MagicMock()
    db._pool.execute = AsyncMock()

    await db.init_schema()

    calls = [str(c) for c in db._pool.execute.call_args_list]
    assert any("causal_chain" in c for c in calls)


async def test_db_init_schema_creates_product_causal_map_table():
    from clawbot.db import Database
    db = Database("postgresql://test/test")
    db._pool = MagicMock()
    db._pool.execute = AsyncMock()

    await db.init_schema()

    calls = [str(c) for c in db._pool.execute.call_args_list]
    assert any("product_causal_map" in c for c in calls)
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_causal_store.py::test_db_init_schema_creates_causal_chain_table -v
pytest tests/test_causal_store.py::test_db_init_schema_creates_product_causal_map_table -v
```

Expected: FAIL — `assert any("causal_chain" ...` fails because tables don't exist.

- [ ] **Step 3: Add tables to `db.py:init_schema()`**

In `src/clawbot/db.py`, append after the `knowledge_category_idx` block:

```python
        await self._pool.execute("""
            CREATE TABLE IF NOT EXISTS causal_chain (
                event_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                chain_id    UUID NOT NULL,
                agent_id    TEXT NOT NULL,
                action_type TEXT NOT NULL,
                causal_depth INTEGER NOT NULL DEFAULT 0,
                ts          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                attributed_revenue_gbp FLOAT NOT NULL DEFAULT 0.0,
                confidence  FLOAT NOT NULL DEFAULT 0.0,
                closed_at   TIMESTAMPTZ,
                metadata    JSONB NOT NULL DEFAULT '{}'
            )
        """)
        await self._pool.execute("""
            CREATE INDEX IF NOT EXISTS causal_chain_agent_ts_idx
            ON causal_chain (agent_id, ts)
        """)
        await self._pool.execute("""
            CREATE INDEX IF NOT EXISTS causal_chain_chain_id_idx
            ON causal_chain (chain_id)
        """)
        await self._pool.execute("""
            CREATE TABLE IF NOT EXISTS product_causal_map (
                gumroad_product_id TEXT PRIMARY KEY,
                chain_id           UUID NOT NULL,
                product_title      TEXT NOT NULL DEFAULT '',
                registered_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_causal_store.py::test_db_init_schema_creates_causal_chain_table tests/test_causal_store.py::test_db_init_schema_creates_product_causal_map_table -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/clawbot/db.py tests/test_causal_store.py
git commit -m "feat: add causal_chain + product_causal_map tables to schema"
```

---

### Task 0.2: CausalStore Core

**Files:**
- Create: `src/clawbot/causal_store.py`
- Test: `tests/test_causal_store.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_causal_store.py`:

```python
import uuid


async def test_record_event_returns_event_id(mock_pool):
    mock_pool.fetchval = AsyncMock(return_value=str(uuid.uuid4()))
    from clawbot.causal_store import CausalStore
    store = CausalStore(mock_pool)
    event_id = await store.record_event(
        chain_id=str(uuid.uuid4()),
        agent_id="ceo",
        action_type="directive",
        causal_depth=0,
    )
    assert event_id is not None
    assert len(event_id) == 36  # UUID string


async def test_close_chain_distributes_revenue_inversely_by_depth(mock_pool):
    chain_id = str(uuid.uuid4())
    event_id_0 = str(uuid.uuid4())
    event_id_1 = str(uuid.uuid4())

    mock_pool.fetch = AsyncMock(return_value=[
        {"event_id": event_id_0, "causal_depth": 0},
        {"event_id": event_id_1, "causal_depth": 1},
    ])

    conn = MagicMock()
    conn.execute = AsyncMock()
    conn.transaction = MagicMock()
    conn.transaction.return_value.__aenter__ = AsyncMock(return_value=None)
    conn.transaction.return_value.__aexit__ = AsyncMock(return_value=None)
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)

    from clawbot.causal_store import CausalStore
    store = CausalStore(mock_pool)
    await store.close_chain(chain_id, revenue_gbp=9.0)

    # depth=0 weight=1.0, depth=1 weight=0.5 → total=1.5
    # depth=0 share = 9.0 * (1.0/1.5) = 6.0
    # depth=1 share = 9.0 * (0.5/1.5) = 3.0
    calls = conn.execute.call_args_list
    shares = [c.args[1] for c in calls]  # second positional arg is the share
    assert abs(shares[0] - 6.0) < 0.01
    assert abs(shares[1] - 3.0) < 0.01


async def test_attributed_revenue_7d_sums_closed_events(mock_pool):
    mock_pool.fetchval = AsyncMock(return_value=42.5)
    from clawbot.causal_store import CausalStore
    store = CausalStore(mock_pool)
    result = await store.attributed_revenue_7d("ceo")
    assert result == pytest.approx(42.5)


async def test_attributed_revenue_7d_returns_zero_on_none(mock_pool):
    mock_pool.fetchval = AsyncMock(return_value=None)
    from clawbot.causal_store import CausalStore
    store = CausalStore(mock_pool)
    result = await store.attributed_revenue_7d("unknown-agent")
    assert result == 0.0


async def test_register_product_and_product_chain_id(mock_pool):
    chain_id = str(uuid.uuid4())
    mock_pool.fetchval = AsyncMock(return_value=chain_id)

    from clawbot.causal_store import CausalStore
    store = CausalStore(mock_pool)
    await store.register_product("prod_abc", chain_id, "UK Tax Guide 2026")
    result = await store.product_chain_id("prod_abc")
    assert result == chain_id
```

- [ ] **Step 2: Run to verify they fail**

```
pytest tests/test_causal_store.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'clawbot.causal_store'`

- [ ] **Step 3: Create `src/clawbot/causal_store.py`**

```python
"""
Per-agent revenue attribution via causal chain tracing.

Every market-signal discovery, executive directive, and executed action is
recorded as a chain event with an increasing causal_depth. When a Gumroad
sale is matched to a product registered in product_causal_map, close_chain()
distributes the sale revenue inversely proportional to depth — the originating
signal (depth=0) earns the largest share; mechanical execution (depth=2+)
earns proportionally less.

Attribution formula:
    weight_i = 1 / (causal_depth_i + 1)
    share_i  = revenue * weight_i / sum(all weights in chain)
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncpg

logger = logging.getLogger(__name__)

_ATTRIBUTION_WINDOW_S = 7 * 86_400


class CausalStore:
    def __init__(self, pool: "asyncpg.Pool") -> None:
        self._pool = pool

    async def record_event(
        self,
        chain_id: str,
        agent_id: str,
        action_type: str,
        causal_depth: int,
        confidence: float = 1.0,
        metadata: dict | None = None,
    ) -> str:
        """Record a causal event. Returns the generated event_id (UUID string)."""
        meta = metadata or {}
        event_id: str = await self._pool.fetchval(
            """
            INSERT INTO causal_chain
                (chain_id, agent_id, action_type, causal_depth, confidence, metadata)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb)
            RETURNING event_id::text
            """,
            chain_id, agent_id, action_type, causal_depth, confidence,
            __import__("json").dumps(meta),
        )
        return event_id

    async def close_chain(self, chain_id: str, revenue_gbp: float) -> None:
        """Distribute revenue_gbp across all open events in chain, weighted inversely
        by causal_depth. Events already closed are skipped."""
        events = await self._pool.fetch(
            "SELECT event_id, causal_depth FROM causal_chain "
            "WHERE chain_id = $1 AND closed_at IS NULL",
            chain_id,
        )
        if not events:
            logger.warning("close_chain: no open events for chain %s", chain_id)
            return
        weights = [1.0 / (row["causal_depth"] + 1) for row in events]
        total = sum(weights)
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                for row, weight in zip(events, weights):
                    share = revenue_gbp * (weight / total)
                    await conn.execute(
                        """UPDATE causal_chain
                           SET attributed_revenue_gbp = $1, closed_at = NOW()
                           WHERE event_id = $2""",
                        share, row["event_id"],
                    )
        logger.info(
            "Closed chain %s: £%.2f distributed across %d events",
            chain_id, revenue_gbp, len(events),
        )

    async def attributed_revenue_7d(self, agent_id: str) -> float:
        """Sum of attributed_revenue_gbp for this agent in the rolling 7-day window."""
        result = await self._pool.fetchval(
            """
            SELECT COALESCE(SUM(attributed_revenue_gbp), 0.0)
            FROM causal_chain
            WHERE agent_id = $1
              AND closed_at IS NOT NULL
              AND ts >= NOW() - INTERVAL '7 days'
            """,
            agent_id,
        )
        return float(result or 0.0)

    async def attribution_rate(self, agent_id: str) -> float:
        """Fraction of chains involving this agent that closed with revenue > 0."""
        total = await self._pool.fetchval(
            "SELECT COUNT(DISTINCT chain_id) FROM causal_chain WHERE agent_id = $1",
            agent_id,
        )
        if not total:
            return 0.0
        with_revenue = await self._pool.fetchval(
            """
            SELECT COUNT(DISTINCT chain_id) FROM causal_chain
            WHERE agent_id = $1
              AND closed_at IS NOT NULL
              AND attributed_revenue_gbp > 0
            """,
            agent_id,
        )
        return float(with_revenue or 0) / float(total)

    async def register_product(
        self,
        gumroad_product_id: str,
        chain_id: str,
        product_title: str,
    ) -> None:
        """Associate a Gumroad product with the causal chain that produced it."""
        await self._pool.execute(
            """
            INSERT INTO product_causal_map (gumroad_product_id, chain_id, product_title)
            VALUES ($1, $2, $3)
            ON CONFLICT (gumroad_product_id) DO UPDATE
            SET chain_id = $2, product_title = $3
            """,
            gumroad_product_id, chain_id, product_title,
        )

    async def product_chain_id(self, gumroad_product_id: str) -> str | None:
        """Return the chain_id for this product, or None if unregistered."""
        result: str | None = await self._pool.fetchval(
            "SELECT chain_id::text FROM product_causal_map WHERE gumroad_product_id = $1",
            gumroad_product_id,
        )
        return result

    async def unattributed_sale_products(
        self,
        sale_product_ids: list[str],
    ) -> list[tuple[str, str]]:
        """Return [(gumroad_product_id, chain_id)] for products with open chains.

        Used by the fitness writer loop to close chains for new Gumroad sales.
        """
        if not sale_product_ids:
            return []
        rows = await self._pool.fetch(
            """
            SELECT p.gumroad_product_id, p.chain_id::text
            FROM product_causal_map p
            WHERE p.gumroad_product_id = ANY($1::text[])
              AND EXISTS (
                SELECT 1 FROM causal_chain c
                WHERE c.chain_id = p.chain_id AND c.closed_at IS NULL
              )
            """,
            sale_product_ids,
        )
        return [(row["gumroad_product_id"], row["chain_id"]) for row in rows]
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_causal_store.py -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/clawbot/causal_store.py tests/test_causal_store.py
git commit -m "feat: add CausalStore — per-agent revenue attribution via causal chain"
```

---

### Task 0.3: OpportunityScanner CAG Integration

**Files:**
- Modify: `src/clawbot/opportunity_scanner.py`
- Test: `tests/test_opportunity_scanner.py` (extend)

The OpportunityScanner needs to:
1. Generate a `chain_id` UUID per discovered opportunity
2. Record a depth-0 chain event (agent_id="scanner", action_type="opportunity_discovered")
3. Write the `chain_id` into the brain metadata alongside the opportunity

- [ ] **Step 1: Write the failing test**

Append to `tests/test_opportunity_scanner.py`:

```python
import uuid
from unittest.mock import AsyncMock, MagicMock, patch


async def test_opportunity_scanner_records_causal_event_on_high_confidence(tmp_path):
    """A high-confidence opportunity must record a depth-0 CAG event."""
    from clawbot.opportunity_scanner import OpportunityScanner

    pool_mock = MagicMock()
    brain = MagicMock()
    brain.write = AsyncMock(return_value=1)

    causal_store = MagicMock()
    causal_store.record_event = AsyncMock(return_value=str(uuid.uuid4()))

    opp = [{"title": "UK AI tax guide", "description": "desc", "confidence": 0.8,
             "time_window_days": 30, "estimated_value": "£100"}]

    scanner = OpportunityScanner(pool=pool_mock, metrics=MagicMock(), brain=brain,
                                 causal_store=causal_store)
    await scanner._write_opportunity_to_brain(opp[0])

    causal_store.record_event.assert_called_once()
    call_kwargs = causal_store.record_event.call_args.kwargs
    assert call_kwargs["agent_id"] == "scanner"
    assert call_kwargs["action_type"] == "opportunity_discovered"
    assert call_kwargs["causal_depth"] == 0


async def test_opportunity_scanner_writes_chain_id_to_brain_metadata(tmp_path):
    """chain_id must be stored in brain metadata so the scheduler can propagate it."""
    from clawbot.opportunity_scanner import OpportunityScanner

    test_chain_id = str(uuid.uuid4())
    brain = MagicMock()
    brain.write = AsyncMock(return_value=1)
    causal_store = MagicMock()
    causal_store.record_event = AsyncMock(return_value=str(uuid.uuid4()))

    opp = {"title": "UK ISA guide", "description": "desc", "confidence": 0.9,
            "time_window_days": 14, "estimated_value": "£50"}

    scanner = OpportunityScanner(
        pool=MagicMock(), metrics=MagicMock(), brain=brain, causal_store=causal_store,
    )
    with patch("uuid.uuid4", return_value=__import__("uuid").UUID(test_chain_id)):
        await scanner._write_opportunity_to_brain(opp)

    brain.write.assert_called_once()
    call_kwargs = brain.write.call_args.kwargs
    assert call_kwargs.get("metadata", {}).get("chain_id") == test_chain_id
```

- [ ] **Step 2: Run to verify they fail**

```
pytest tests/test_opportunity_scanner.py::test_opportunity_scanner_records_causal_event_on_high_confidence -v
pytest tests/test_opportunity_scanner.py::test_opportunity_scanner_writes_chain_id_to_brain_metadata -v
```

Expected: FAIL — `OpportunityScanner.__init__` has no `causal_store` param; `_write_opportunity_to_brain` doesn't exist yet.

- [ ] **Step 3: Update `src/clawbot/opportunity_scanner.py`**

In the `__init__` method of `OpportunityScanner`, add `causal_store` param:

```python
# Add to imports at top of file:
import uuid

# Update __init__:
class OpportunityScanner:
    def __init__(
        self,
        pool: "LLMPool",
        metrics: MetricsStore,
        brain: "CompanyBrain | None" = None,
        causal_store: "CausalStore | None" = None,
    ) -> None:
        self._pool = pool
        self._metrics = metrics
        self._brain = brain
        self._causal_store = causal_store
        self._backoff_state: dict[str, tuple[int, float]] = {}
```

Add the `_write_opportunity_to_brain` method (find where brain writes happen in the existing code and extract/extend):

```python
    async def _write_opportunity_to_brain(self, opp: dict) -> None:
        """Write a single opportunity to brain with CAG chain_id in metadata."""
        chain_id = str(uuid.uuid4())
        if self._causal_store is not None:
            try:
                await self._causal_store.record_event(
                    chain_id=chain_id,
                    agent_id="scanner",
                    action_type="opportunity_discovered",
                    causal_depth=0,
                    confidence=float(opp.get("confidence", 1.0)),
                    metadata={"title": opp.get("title", "")},
                )
            except Exception as exc:
                logger.warning("CAG record_event failed (non-fatal): %s", exc)
        if self._brain is not None:
            content = (
                f"Opportunity: {opp.get('title', '')} — {opp.get('description', '')}"
                f" (confidence: {opp.get('confidence', 0):.2f},"
                f" window: {opp.get('time_window_days', 0)}d,"
                f" value: {opp.get('estimated_value', 'unknown')})"
            )
            try:
                await self._brain.write(
                    content,
                    category="market_signal",
                    metadata={"chain_id": chain_id, "title": opp.get("title", "")},
                )
            except Exception as exc:
                logger.warning("Brain write failed (non-fatal): %s", exc)
```

Now find existing brain-write calls in `_score_source()` or wherever opportunities are written to brain, and replace them with `await self._write_opportunity_to_brain(opp)`.

Read the relevant section of opportunity_scanner.py to find the brain write:

```python
# Locate the _score_source or scan loop that calls brain.write and replace with
# calls to _write_opportunity_to_brain. The pattern to find:
#   await self._brain.write(content, category="market_signal")
# Replace with:
#   await self._write_opportunity_to_brain(opp)
```

Note: Check `src/clawbot/opportunity_scanner.py` lines 160+ for the existing brain write code and update it to call `_write_opportunity_to_brain`.

- [ ] **Step 4: Also check CompanyBrain.write signature accepts metadata kwarg**

```python
# In src/clawbot/company_brain.py, verify:
# async def write(self, content: str, category: str = "", metadata: dict | None = None) -> int
# If metadata param is missing, add it.
```

- [ ] **Step 5: Run tests to verify they pass**

```
pytest tests/test_opportunity_scanner.py -v
```

Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add src/clawbot/opportunity_scanner.py src/clawbot/company_brain.py tests/test_opportunity_scanner.py
git commit -m "feat: opportunity scanner generates CAG chain_id per discovery"
```

---

## Phase 1 — Distributed Fitness

### Task 1.1: Extend FitnessScore for Attribution

**Files:**
- Modify: `src/clawbot/fitness.py`
- Test: `tests/test_fitness.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_fitness.py`:

```python
def test_fitness_score_has_attribution_fields():
    """FitnessScore must carry attributed_revenue and attribution_rate."""
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
    """Attribution fields are informational — they must not alter the score computation."""
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
```

- [ ] **Step 2: Run to verify they fail**

```
pytest tests/test_fitness.py::test_fitness_score_has_attribution_fields -v
```

Expected: FAIL — `TypeError: compute_fitness() got unexpected keyword argument 'attributed_revenue_7d_gbp'`

- [ ] **Step 3: Update `src/clawbot/fitness.py`**

```python
@dataclass
class FitnessScore:
    agent_id: str
    revenue_7d_gbp: float
    tasks_completed: int
    tasks_failed: int
    avg_latency_s: float
    score: float
    attributed_revenue_7d_gbp: float = 0.0
    attribution_rate: float = 0.0


def compute_fitness(
    agent_id: str,
    revenue_7d_gbp: float,
    tasks_completed: int,
    tasks_failed: int,
    avg_latency_s: float,
    latency_ceiling_s: float = 120.0,
    attributed_revenue_7d_gbp: float = 0.0,
    attribution_rate: float = 0.0,
) -> FitnessScore:
    # ... (existing scoring logic unchanged) ...
    # At the end, pass the new fields through:
    return FitnessScore(
        agent_id=agent_id,
        revenue_7d_gbp=revenue_7d_gbp,
        tasks_completed=tasks_completed,
        tasks_failed=tasks_failed,
        avg_latency_s=avg_latency_s,
        score=round(raw, 4),
        attributed_revenue_7d_gbp=attributed_revenue_7d_gbp,
        attribution_rate=attribution_rate,
    )
```

Also update `save_fitness()` to write the new fields and `load_fitness_from_metrics()` to handle missing keys with `.get()` defaults (backward-compat with existing fitness.json files):

```python
def save_fitness(metrics_dir: Path, fitness: FitnessScore) -> None:
    agent_dir = metrics_dir / fitness.agent_id
    agent_dir.mkdir(parents=True, exist_ok=True)
    path = agent_dir / "fitness.json"
    path.write_text(
        json.dumps({
            "agent_id": fitness.agent_id,
            "revenue_7d_gbp": fitness.revenue_7d_gbp,
            "tasks_completed": fitness.tasks_completed,
            "tasks_failed": fitness.tasks_failed,
            "avg_latency_s": fitness.avg_latency_s,
            "score": fitness.score,
            "attributed_revenue_7d_gbp": fitness.attributed_revenue_7d_gbp,
            "attribution_rate": fitness.attribution_rate,
        }, indent=2),
        encoding="utf-8",
    )


def load_fitness_from_metrics(metrics_dir: Path, agent_id: str) -> FitnessScore | None:
    path = metrics_dir / agent_id / "fitness.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return FitnessScore(
        agent_id=data["agent_id"],
        revenue_7d_gbp=data["revenue_7d_gbp"],
        tasks_completed=data["tasks_completed"],
        tasks_failed=data["tasks_failed"],
        avg_latency_s=data["avg_latency_s"],
        score=data["score"],
        attributed_revenue_7d_gbp=data.get("attributed_revenue_7d_gbp", 0.0),
        attribution_rate=data.get("attribution_rate", 0.0),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_fitness.py -v
```

Expected: all PASS (including existing tests — no regressions)

- [ ] **Step 5: Commit**

```bash
git add src/clawbot/fitness.py tests/test_fitness.py
git commit -m "feat: add attributed_revenue_7d_gbp + attribution_rate to FitnessScore"
```

---

### Task 1.2: Fitness Writer Uses Attributed Revenue

**Files:**
- Modify: `src/clawbot/fitness_writer.py`
- Modify: `src/clawbot/scheduler.py:869-880` (`_fitness_writer_loop`)
- Test: `tests/test_fitness_writer.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_fitness_writer.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock


async def test_refresh_all_fitness_uses_attributed_revenue_when_causal_store_provided(tmp_path):
    """When causal_store is given, each agent gets its own attributed share, not equal-split."""
    from clawbot.fitness_writer import append_observation, refresh_all_fitness
    import time

    for agent_id, duration, success in [("ceo", 5.0, True), ("cfo", 3.0, True)]:
        append_observation(tmp_path, agent_id, duration, success)

    causal_store = MagicMock()
    # CEO attributed £8, CFO attributed £2
    async def fake_attributed(agent_id):
        return 8.0 if agent_id == "ceo" else 2.0
    causal_store.attributed_revenue_7d = fake_attributed
    async def fake_rate(agent_id):
        return 0.8 if agent_id == "ceo" else 0.4
    causal_store.attribution_rate = fake_rate

    results = await refresh_all_fitness(tmp_path, total_revenue_7d_gbp=10.0,
                                        causal_store=causal_store)

    assert results["ceo"] is not None
    assert results["cfo"] is not None
    assert results["ceo"].attributed_revenue_7d_gbp == pytest.approx(8.0)
    assert results["cfo"].attributed_revenue_7d_gbp == pytest.approx(2.0)


async def test_refresh_all_fitness_falls_back_to_equal_share_without_causal_store(tmp_path):
    """Without causal_store, equal-split behaviour is preserved."""
    from clawbot.fitness_writer import append_observation, refresh_all_fitness

    for agent_id in ("ceo", "cfo"):
        append_observation(tmp_path, agent_id, 5.0, True)

    results = await refresh_all_fitness(tmp_path, total_revenue_7d_gbp=10.0)

    assert results["ceo"] is not None
    assert results["cfo"] is not None
    # Equal share = £5 each → attributed_revenue_7d_gbp defaults to 0.0 (not queried)
    assert results["ceo"].attributed_revenue_7d_gbp == pytest.approx(0.0)
```

- [ ] **Step 2: Run to verify they fail**

```
pytest tests/test_fitness_writer.py::test_refresh_all_fitness_uses_attributed_revenue_when_causal_store_provided -v
```

Expected: FAIL — `refresh_all_fitness()` doesn't accept `causal_store` param and isn't async.

- [ ] **Step 3: Update `src/clawbot/fitness_writer.py`**

Change `refresh_all_fitness` signature to async and accept optional `causal_store`:

```python
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from clawbot.causal_store import CausalStore


async def refresh_all_fitness(
    metrics_dir: Path,
    total_revenue_7d_gbp: float,
    causal_store: "CausalStore | None" = None,
) -> dict[str, FitnessScore | None]:
    """Recompute fitness.json for every agent with observations.

    If causal_store is provided, each agent receives its attributed revenue share
    from the CAG. Otherwise falls back to the equal-split heuristic.
    """
    agents = list_active_agents(metrics_dir)
    active_with_obs = []
    for agent_id in agents:
        if read_recent_observations(metrics_dir, agent_id):
            active_with_obs.append(agent_id)
            trim_observations(metrics_dir, agent_id)
    if not active_with_obs:
        return {}

    results: dict[str, FitnessScore | None] = {}
    if causal_store is not None:
        for agent_id in active_with_obs:
            attributed = await causal_store.attributed_revenue_7d(agent_id)
            rate = await causal_store.attribution_rate(agent_id)
            results[agent_id] = compute_and_save_fitness(
                metrics_dir, agent_id,
                revenue_share_gbp=total_revenue_7d_gbp / len(active_with_obs),
                attributed_revenue_7d_gbp=attributed,
                attribution_rate=rate,
            )
    else:
        share = total_revenue_7d_gbp / len(active_with_obs)
        for agent_id in active_with_obs:
            results[agent_id] = compute_and_save_fitness(metrics_dir, agent_id, share)
    return results
```

Also update `compute_and_save_fitness()` to accept and forward the new fields:

```python
def compute_and_save_fitness(
    metrics_dir: Path,
    agent_id: str,
    revenue_share_gbp: float,
    attributed_revenue_7d_gbp: float = 0.0,
    attribution_rate: float = 0.0,
) -> FitnessScore | None:
    obs = read_recent_observations(metrics_dir, agent_id)
    if not obs:
        return None
    tasks_completed = sum(1 for o in obs if o.success)
    tasks_failed = sum(1 for o in obs if not o.success)
    avg_latency = sum(o.duration_s for o in obs) / max(1, len(obs))
    score = compute_fitness(
        agent_id=agent_id,
        revenue_7d_gbp=revenue_share_gbp,
        tasks_completed=tasks_completed,
        tasks_failed=tasks_failed,
        avg_latency_s=avg_latency,
        attributed_revenue_7d_gbp=attributed_revenue_7d_gbp,
        attribution_rate=attribution_rate,
    )
    save_fitness(metrics_dir, score)
    return score
```

- [ ] **Step 4: Update `scheduler.py:_fitness_writer_loop` to await the now-async function and pass causal_store**

```python
async def _fitness_writer_loop(self) -> None:
    while True:
        await asyncio.sleep(FITNESS_WRITER_INTERVAL_S)
        try:
            from clawbot.fitness_writer import refresh_all_fitness
            metrics = await self._load_metrics()
            revenue = float(metrics.get("revenue_7d_gbp", 0.0))
            results = await refresh_all_fitness(
                self._metrics_dir, revenue,
                causal_store=getattr(self, "_causal_store", None),
            )
            logger.info("Fitness refreshed for %d agents", len(results))
        except Exception as exc:
            logger.error("Fitness writer cycle failed: %s", exc)
```

- [ ] **Step 5: Run tests to verify they pass**

```
pytest tests/test_fitness_writer.py -v
```

Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add src/clawbot/fitness_writer.py src/clawbot/scheduler.py tests/test_fitness_writer.py
git commit -m "feat: fitness writer uses per-agent attributed revenue from CausalStore"
```

---

## Phase 2 — Execution Kernel

**Sequencing rationale:** DirectiveRouter activates the execution capability. It must be installed after attribution (Phase 0–1) so that every action it executes is immediately traceable.

### Task 2.1: Extract json_util

**Files:**
- Create: `src/clawbot/json_util.py`
- Modify: `src/clawbot/scheduler.py` (replace local `_extract_json` with import)
- Test: `tests/test_directive_router.py` (added in 2.2; json_util tested inline)

- [ ] **Step 1: Create `src/clawbot/json_util.py`**

```python
"""Shared JSON extraction utility. Used by scheduler and directive_router."""
import json
import re


def extract_json(text: str) -> dict:
    """Return the first JSON object in text, stripping markdown fences if present.

    Raises ValueError if no JSON object is found or it fails to parse.
    """
    match = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
    blob = match.group(1) if match else text
    start = blob.find("{")
    end = blob.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object found in text")
    return json.loads(blob[start: end + 1])
```

- [ ] **Step 2: Update `scheduler.py` to import from `json_util` instead of using local `_extract_json`**

Find the local `_extract_json` function (around line 81) and remove it. Add to imports:

```python
from clawbot.json_util import extract_json as _extract_json
```

Search for all uses of `_extract_json` in scheduler.py — replace with `_extract_json` (name unchanged, just now imported).

- [ ] **Step 3: Run existing tests to verify no regressions**

```
pytest tests/test_scheduler.py -v
```

Expected: all PASS

- [ ] **Step 4: Commit**

```bash
git add src/clawbot/json_util.py src/clawbot/scheduler.py
git commit -m "refactor: extract _extract_json to json_util.py"
```

---

### Task 2.2: DirectiveRouter — Core + Action Dispatch

**Files:**
- Create: `src/clawbot/directive_router.py`
- Test: `tests/test_directive_router.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_directive_router.py
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def make_bus(messages_by_topic: dict[str, list[dict]]):
    bus = MagicMock()
    async def fake_read(topic, consumer_id, count=10, block_ms=5000):
        return messages_by_topic.get(topic, [])
    bus.read = fake_read
    bus.ack = AsyncMock()
    bus.publish = AsyncMock()
    return bus


def make_directive_msg(action: str, directive: str = "test", chain_id: str | None = None):
    import json
    chain_id = chain_id or str(uuid.uuid4())
    payload = json.dumps({"action": action, "directive": directive, "priority": "high"})
    return {
        "_id": "1-1",
        "response": f"```json\n{payload}\n```",
        "chain_id": chain_id,
        "ts": "2026-01-01T00:00:00Z",
    }


async def test_directive_router_acks_on_successful_dispatch():
    from clawbot.directive_router import DirectiveRouter

    msg = make_directive_msg("message", directive="hello worker")
    bus = make_bus({"ceo.directive": [msg]})

    causal_store = MagicMock()
    causal_store.record_event = AsyncMock(return_value=str(uuid.uuid4()))

    router = DirectiveRouter(
        bus=bus,
        causal_store=causal_store,
        registry=MagicMock(),
        agent_factory=MagicMock(),
        task_store=MagicMock(),
        metrics_dir=MagicMock(),
    )

    # Run one poll cycle
    await router._poll_once()

    bus.ack.assert_called_once_with("ceo.directive", "1-1")


async def test_directive_router_does_not_ack_on_handler_failure():
    """Handler exception must not ack — message stays in pending for retry."""
    from clawbot.directive_router import DirectiveRouter

    msg = make_directive_msg("hire")
    bus = make_bus({"ceo.directive": [msg]})

    causal_store = MagicMock()
    causal_store.record_event = AsyncMock(side_effect=RuntimeError("db down"))

    router = DirectiveRouter(
        bus=bus, causal_store=causal_store, registry=MagicMock(),
        agent_factory=MagicMock(), task_store=MagicMock(), metrics_dir=MagicMock(),
    )
    await router._poll_once()

    bus.ack.assert_not_called()


async def test_directive_router_acks_malformed_json():
    """Unparseable responses must be acked immediately — retry is futile."""
    from clawbot.directive_router import DirectiveRouter

    msg = {"_id": "2-2", "response": "not json at all", "chain_id": str(uuid.uuid4()), "ts": ""}
    bus = make_bus({"ceo.directive": [msg]})

    router = DirectiveRouter(
        bus=bus, causal_store=MagicMock(), registry=MagicMock(),
        agent_factory=MagicMock(), task_store=MagicMock(), metrics_dir=MagicMock(),
    )
    await router._poll_once()

    bus.ack.assert_called_once_with("ceo.directive", "2-2")


async def test_directive_router_records_causal_events_for_known_action():
    from clawbot.directive_router import DirectiveRouter

    chain_id = str(uuid.uuid4())
    msg = make_directive_msg("message", directive="Hello", chain_id=chain_id)
    bus = make_bus({"ceo.directive": [msg]})

    causal_store = MagicMock()
    causal_store.record_event = AsyncMock(return_value=str(uuid.uuid4()))

    router = DirectiveRouter(
        bus=bus, causal_store=causal_store, registry=MagicMock(),
        agent_factory=MagicMock(), task_store=MagicMock(), metrics_dir=MagicMock(),
    )
    await router._poll_once()

    # Two events: directive (depth=0) + action (depth=1)
    assert causal_store.record_event.call_count == 2
    depths = [c.kwargs["causal_depth"] for c in causal_store.record_event.call_args_list]
    assert 0 in depths
    assert 1 in depths
```

- [ ] **Step 2: Run to verify they fail**

```
pytest tests/test_directive_router.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'clawbot.directive_router'`

- [ ] **Step 3: Create `src/clawbot/directive_router.py`**

```python
"""
Execution kernel — the only component that converts directives into real actions.

Subscribes to all *.directive bus topics. For each message:
1. Records a depth-0 chain event (executive issued directive)
2. Parses the action field
3. Dispatches to the registered handler
4. Records a depth-1 chain event (action executed)
5. Acks the message only on full success

At-least-once delivery: the ack is conditional on success. A handler failure
leaves the message in the Redis pending list for the next poll. This prevents
silent directive loss at the cost of possible duplicate execution on recovery —
all handlers must be idempotent.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from clawbot.json_util import extract_json

if TYPE_CHECKING:
    from clawbot.agent_factory import AgentFactory
    from clawbot.agent_registry import AgentRegistry
    from clawbot.bus import MessageBus
    from clawbot.causal_store import CausalStore
    from clawbot.task_store import TaskStore

logger = logging.getLogger(__name__)

DIRECTIVE_TOPICS = [
    "ceo.directive", "cfo.directive", "cmo.directive",
    "coo.directive", "cto.directive",
]
_POLL_BLOCK_MS = 200
_UNKNOWN_CHAIN = "00000000-0000-0000-0000-000000000000"


class DirectiveRouter:
    def __init__(
        self,
        bus: "MessageBus",
        causal_store: "CausalStore",
        registry: "AgentRegistry",
        agent_factory: "AgentFactory",
        task_store: "TaskStore",
        metrics_dir: Path,
    ) -> None:
        self._bus = bus
        self._causal_store = causal_store
        self._registry = registry
        self._factory = agent_factory
        self._task_store = task_store
        self._metrics_dir = metrics_dir

    async def run(self) -> None:
        """Continuous poll loop. Runs until cancelled."""
        while True:
            await self._poll_once()
            await asyncio.sleep(0)  # yield to other tasks

    async def _poll_once(self) -> None:
        """One pass across all directive topics."""
        for topic in DIRECTIVE_TOPICS:
            try:
                messages = await self._bus.read(
                    topic, "directive-router", count=5, block_ms=_POLL_BLOCK_MS,
                )
            except Exception as exc:
                logger.error("Bus read failed for topic %s: %s", topic, exc)
                continue
            for msg in messages:
                await self._handle_message(topic, msg)

    async def _handle_message(self, topic: str, msg: dict) -> None:
        msg_id: str = msg["_id"]
        chain_id: str = msg.get("chain_id") or _UNKNOWN_CHAIN
        from_agent = topic.split(".")[0]  # "ceo", "cfo", etc.

        try:
            data = extract_json(msg.get("response", ""))
        except (ValueError, Exception):
            logger.warning("DirectiveRouter: malformed JSON in %s — acking to clear", topic)
            await self._bus.ack(topic, msg_id)
            return

        action = str(data.get("action", "")).strip().lower()
        if not action:
            await self._bus.ack(topic, msg_id)
            return

        # Record depth=0 event: executive issued this directive
        try:
            await self._causal_store.record_event(
                chain_id=chain_id,
                agent_id=from_agent,
                action_type="directive",
                causal_depth=0,
            )
        except Exception as exc:
            logger.error("CAG depth-0 record failed for chain %s: %s", chain_id, exc)
            # Do NOT ack — leave for retry
            return

        handler = self._get_handler(action)
        if handler is None:
            logger.warning("DirectiveRouter: unknown action '%s' from %s", action, from_agent)
            await self._bus.ack(topic, msg_id)
            return

        try:
            await handler(data, chain_id, from_agent)
            # Record depth=1 event: action executed
            await self._causal_store.record_event(
                chain_id=chain_id,
                agent_id="router",
                action_type=action,
                causal_depth=1,
                metadata={"directive": str(data.get("directive", ""))[:200]},
            )
            await self._bus.ack(topic, msg_id)
        except Exception as exc:
            logger.error(
                "DirectiveRouter: handler '%s' failed for chain %s: %s",
                action, chain_id, exc,
            )
            # Do NOT ack

    def _get_handler(self, action: str):
        return {
            "hire": self._handle_hire,
            "fire": self._handle_fire,
            "assign_task": self._handle_assign_task,
            "publish_product": self._handle_publish_product,
            "message": self._handle_message_action,
        }.get(action)

    async def _handle_hire(self, data: dict, chain_id: str, from_agent: str) -> None:
        role = str(data.get("role", data.get("directive", "analyst")))[:80]
        mandate = str(data.get("mandate", data.get("directive", "Generate revenue.")))[:400]
        supervisor = str(data.get("supervisor", from_agent))[:40]
        from clawbot.llm_pool import LLMPool  # avoid circular at module level
        await self._factory.spawn(
            role=role,
            supervisor=supervisor,
            mandate=mandate,
            pool=getattr(self._factory, "_pool", None),
        )
        logger.info("Hired new agent: role=%s supervisor=%s", role, supervisor)

    async def _handle_fire(self, data: dict, chain_id: str, from_agent: str) -> None:
        agent_id = str(data.get("agent_id", data.get("directive", "")))[:60]
        if not agent_id:
            raise ValueError("fire action missing agent_id")
        await self._factory.fire(agent_id)
        logger.info("Fired agent: %s", agent_id)

    async def _handle_assign_task(self, data: dict, chain_id: str, from_agent: str) -> None:
        assigned_to = str(data.get("assigned_to", ""))[:60]
        title = str(data.get("title", data.get("directive", "task")))[:120]
        description = str(data.get("description", data.get("directive", "")))[:1000]
        if not assigned_to:
            raise ValueError("assign_task missing assigned_to")
        await self._task_store.create_task(
            title=title,
            description=description,
            assigned_to=assigned_to,
            chain_id=chain_id,
        )
        logger.info("Assigned task '%s' to %s", title, assigned_to)

    async def _handle_publish_product(self, data: dict, chain_id: str, from_agent: str) -> None:
        title = str(data.get("title", data.get("directive", "new product")))[:200]
        description = str(data.get("description", ""))[:2000]
        from clawbot.escalation import escalate
        await escalate(
            bus=self._bus,
            severity="request",
            summary=f"New product needs Gumroad listing: {title}",
            detail=(
                f"Product title: {title}\n\n"
                f"Description: {description}\n\n"
                f"CAG chain_id: {chain_id}\n\n"
                "Action: Create this product in the Gumroad dashboard at "
                "https://app.gumroad.com/products/new, then reply with the "
                "product URL so the system can register it for revenue attribution.\n"
                "Reply format: PRODUCT_URL:<url> CHAIN:<chain_id>"
            ),
            from_agent=from_agent,
        )
        logger.info("Escalated publish_product for '%s' (chain=%s)", title, chain_id)

    async def _handle_message_action(self, data: dict, chain_id: str, from_agent: str) -> None:
        target = str(data.get("target", data.get("assigned_to", "")))[:60]
        content = str(data.get("message", data.get("directive", "")))[:1000]
        if not target:
            raise ValueError("message action missing target")
        await self._bus.publish(
            f"inbox.{target}",
            {"from": from_agent, "message": content, "chain_id": chain_id},
        )
        logger.info("Sent message from %s to %s", from_agent, target)
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_directive_router.py -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/clawbot/directive_router.py tests/test_directive_router.py
git commit -m "feat: DirectiveRouter — execution kernel with CAG recording + at-least-once delivery"
```

---

### Task 2.3: Scheduler Wires DirectiveRouter + chain_id in Directives

**Files:**
- Modify: `src/clawbot/scheduler.py`
- Test: `tests/test_scheduler_selfschedule.py` (new, also covers chain_id presence)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_scheduler_selfschedule.py
import json
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def make_scheduler(bus_publish_log=None):
    from clawbot.scheduler import Scheduler
    pool = MagicMock()
    pool.complete = AsyncMock(return_value='{"action": "wait", "directive": "nothing", "priority": "low"}')
    bus = MagicMock()
    bus.publish = AsyncMock(side_effect=lambda topic, payload: (
        bus_publish_log.append((topic, payload)) if bus_publish_log is not None else None
    ))
    monitor = MagicMock()
    monitor.should_halt = AsyncMock(return_value=False)
    monitor.spend_limit_reached = AsyncMock(return_value=False)
    s = Scheduler(pool=pool, bus=bus, monitor=monitor)
    s._metrics_dir = MagicMock()
    s._metrics_dir.__truediv__ = lambda self, x: MagicMock(
        exists=lambda: False,
        read_text=lambda encoding=None: "SOUL",
    )
    return s, bus


async def test_directive_bus_message_includes_chain_id():
    """Every directive published to *.directive must carry a chain_id UUID."""
    log = []
    s, bus = make_scheduler(bus_publish_log=log)

    agents_dir = MagicMock()
    soul_file = MagicMock()
    soul_file.exists.return_value = True
    soul_file.read_text.return_value = "# SOUL"
    agents_dir.__truediv__ = lambda self, x: MagicMock(
        __truediv__=lambda self2, y: soul_file
    )
    s._agents_dir = agents_dir

    with patch("clawbot.scheduler.append_observation"):
        with patch.object(s, "_load_metrics", AsyncMock(return_value={"revenue_7d_gbp": 0.0})):
            with patch.object(s, "_brain_recall", AsyncMock(return_value="")):
                with patch.object(s, "_brain_remember", AsyncMock()):
                    with patch.object(s, "_write_company_metrics", AsyncMock()):
                        with patch.object(s, "_record_variant_observation", AsyncMock()):
                            await s._run_executive_cycle()

    directive_publishes = [(t, p) for t, p in log if t == "ceo.directive"]
    assert len(directive_publishes) == 1
    payload = directive_publishes[0][1]
    assert "chain_id" in payload
    # Verify it's a valid UUID
    uuid.UUID(payload["chain_id"])
```

- [ ] **Step 2: Run to verify it fails**

```
pytest tests/test_scheduler_selfschedule.py::test_directive_bus_message_includes_chain_id -v
```

Expected: FAIL — `KeyError: 'chain_id'` (directive payload doesn't include chain_id yet)

- [ ] **Step 3: Update `scheduler.py:_run_executive_cycle()` and `_run_lieutenant_cycle()`**

In both methods, generate `chain_id` and include in the bus publish:

```python
import uuid as _uuid  # add to top-level imports

# In _run_executive_cycle, find the bus publish line:
#   await self._bus.publish("ceo.directive", {"response": response, "ts": ..., "variant": variant})
# Replace with:
    chain_id = str(_uuid.uuid4())
    await self._bus.publish(
        "ceo.directive",
        {"response": response, "ts": datetime.now(UTC).isoformat(),
         "variant": variant, "chain_id": chain_id},
    )

# Same pattern in _run_lieutenant_cycle:
    chain_id = str(_uuid.uuid4())
    await self._bus.publish(
        f"{agent_id}.directive",
        {"response": response, "ts": datetime.now(UTC).isoformat(),
         "variant": variant, "chain_id": chain_id},
    )
```

- [ ] **Step 4: Add DirectiveRouter loop to `Scheduler.__init__` and `run_forever()`**

In `Scheduler.__init__`, add:
```python
from clawbot.agent_factory import AgentFactory

# Add to __init__ signature:
causal_store: "CausalStore | None" = None,
task_store: "TaskStore | None" = None,

# In __init__ body:
self._causal_store = causal_store
self._task_store = task_store
```

In `run_forever()`, after the other task creations:
```python
if self._causal_store is not None and self._registry is not None:
    from clawbot.directive_router import DirectiveRouter
    from clawbot.agent_factory import AgentFactory
    from clawbot.task_store import TaskStore
    factory = AgentFactory(registry=self._registry, agents_dir=self._agents_dir)
    # Inject pool into factory for spawn()
    factory._pool = self._pool
    task_store = self._task_store or TaskStore(self._metrics_dir / "tasks")
    router = DirectiveRouter(
        bus=self._bus,
        causal_store=self._causal_store,
        registry=self._registry,
        agent_factory=factory,
        task_store=task_store,
        metrics_dir=self._metrics_dir,
    )
    tasks.append(asyncio.create_task(router.run(), name="directive-router"))
    for topic in DIRECTIVE_TOPICS:
        await self._bus.subscribe(topic)
```

Also add the import at the top of the scheduler file:
```python
from clawbot.directive_router import DIRECTIVE_TOPICS
```

- [ ] **Step 5: Update executive prompt to include action vocabulary**

In both `_run_executive_cycle()` and `_run_lieutenant_cycle()`, update the user message to include the action vocabulary:

```python
_ACTION_VOCAB = (
    '{"action": "hire", "role": "...", "mandate": "...", "supervisor": "..."} '
    '| {"action": "fire", "agent_id": "..."} '
    '| {"action": "assign_task", "assigned_to": "<agent_id>", "title": "...", "description": "..."} '
    '| {"action": "publish_product", "title": "...", "description": "..."} '
    '| {"action": "message", "target": "<agent_id>", "message": "..."} '
    '| {"action": "wait", "directive": "reason"}'
)

# Replace the user message content's "Output JSON:" prompt with:
f"What is your next action? Output JSON with one of these action schemas:\n{_ACTION_VOCAB}\n"
f"Add: \"priority\": \"high|medium|low\", \"next_wakeup_s\": <integer 60-1800> "
f"(how many seconds until your next cycle — set lower when urgent, higher when waiting), "
f"\"escalate\": null | {{\"severity\": \"...\", \"summary\": \"...\", \"detail\": \"...\"}}"
```

- [ ] **Step 6: Run tests**

```
pytest tests/test_scheduler_selfschedule.py tests/test_scheduler.py -v
```

Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add src/clawbot/scheduler.py tests/test_scheduler_selfschedule.py
git commit -m "feat: wire DirectiveRouter into scheduler; add chain_id to all directives"
```

---

## Phase 3 — Task Bidirectional Visibility (Blocking Dependency)

**Why blocking:** Workers run `_worker_agent_loop()` which asks "what is your next action?" without ever reading their task queue. Directives assigned via `assign_task` vanish. The `DirectiveRouter._handle_assign_task` handler records a task in `TaskStore`, but the worker has no mechanism to read it. This phase closes the loop.

### Task 3.1: TaskStore

**Files:**
- Create: `src/clawbot/task_store.py`
- Test: `tests/test_task_store.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_task_store.py
import pytest
import json
from pathlib import Path


def test_task_store_create_and_read(tmp_path):
    from clawbot.task_store import TaskStore
    store = TaskStore(tmp_path)
    store.create_task(title="Write UK ISA guide", description="...",
                      assigned_to="worker-001", chain_id="abc-123")

    tasks = store.read_tasks("worker-001")
    assert len(tasks) == 1
    assert tasks[0]["title"] == "Write UK ISA guide"
    assert tasks[0]["chain_id"] == "abc-123"
    assert tasks[0]["status"] == "pending"


def test_task_store_complete_task(tmp_path):
    from clawbot.task_store import TaskStore
    store = TaskStore(tmp_path)
    store.create_task("task A", "desc", "worker-001", "chain-1")

    tasks = store.read_tasks("worker-001")
    task_id = tasks[0]["task_id"]
    store.complete_task(task_id, "worker-001")

    pending = store.read_tasks("worker-001")
    assert len(pending) == 0


def test_task_store_fail_task(tmp_path):
    from clawbot.task_store import TaskStore
    store = TaskStore(tmp_path)
    store.create_task("task B", "desc", "worker-001", "chain-1")

    tasks = store.read_tasks("worker-001")
    task_id = tasks[0]["task_id"]
    store.fail_task(task_id, "worker-001", reason="LLM timeout")

    pending = store.read_tasks("worker-001")
    assert len(pending) == 0


def test_task_store_read_tasks_returns_empty_for_unknown_agent(tmp_path):
    from clawbot.task_store import TaskStore
    store = TaskStore(tmp_path)
    assert store.read_tasks("nobody") == []


def test_task_store_multiple_agents_isolated(tmp_path):
    from clawbot.task_store import TaskStore
    store = TaskStore(tmp_path)
    store.create_task("task for A", "desc", "agent-A", "chain-1")
    store.create_task("task for B", "desc", "agent-B", "chain-2")

    assert len(store.read_tasks("agent-A")) == 1
    assert len(store.read_tasks("agent-B")) == 1
    assert store.read_tasks("agent-A")[0]["title"] == "task for A"
```

- [ ] **Step 2: Run to verify they fail**

```
pytest tests/test_task_store.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'clawbot.task_store'`

- [ ] **Step 3: Create `src/clawbot/task_store.py`**

```python
"""
JSONL-backed per-agent task queue.

Tasks are created by DirectiveRouter.assign_task, read by workers before each
cycle, and completed/failed by workers after execution. Two files per agent:
- tasks_dir/<agent_id>/pending.jsonl  — unstarted and in-progress tasks
- tasks_dir/<agent_id>/completed.jsonl — archive of done/failed (append-only)

Concurrent access: single-process only (no file locking). The scheduler runs
all agent loops in the same process as a set of asyncio coroutines — no
cross-process writes occur in the current architecture.
"""
from __future__ import annotations

import json
import time
import uuid
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class TaskStore:
    def __init__(self, tasks_dir: Path) -> None:
        self._dir = tasks_dir

    def _agent_dir(self, agent_id: str) -> Path:
        d = self._dir / agent_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def create_task(
        self,
        title: str,
        description: str,
        assigned_to: str,
        chain_id: str,
    ) -> str:
        task_id = str(uuid.uuid4())
        task = {
            "task_id": task_id,
            "title": title[:200],
            "description": description[:2000],
            "assigned_to": assigned_to,
            "chain_id": chain_id,
            "status": "pending",
            "created_at": time.time(),
        }
        pending_path = self._agent_dir(assigned_to) / "pending.jsonl"
        with pending_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(task) + "\n")
        return task_id

    def read_tasks(self, agent_id: str) -> list[dict]:
        """Return all pending tasks for this agent."""
        path = self._agent_dir(agent_id) / "pending.jsonl"
        if not path.exists():
            return []
        tasks = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                t = json.loads(line)
                if t.get("status") == "pending":
                    tasks.append(t)
            except (json.JSONDecodeError, KeyError):
                continue
        return tasks

    def complete_task(self, task_id: str, agent_id: str) -> None:
        self._update_task(task_id, agent_id, status="completed")

    def fail_task(self, task_id: str, agent_id: str, reason: str = "") -> None:
        self._update_task(task_id, agent_id, status="failed", reason=reason)

    def _update_task(self, task_id: str, agent_id: str, **updates) -> None:
        path = self._agent_dir(agent_id) / "pending.jsonl"
        if not path.exists():
            return
        kept: list[str] = []
        found = None
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                t = json.loads(line)
                if t.get("task_id") == task_id:
                    t.update(updates)
                    t["updated_at"] = time.time()
                    found = t
                else:
                    kept.append(line)
            except (json.JSONDecodeError, KeyError):
                kept.append(line)

        path.write_text(
            "\n".join(kept) + ("\n" if kept else ""),
            encoding="utf-8",
        )
        if found is not None:
            archive = self._agent_dir(agent_id) / "completed.jsonl"
            with archive.open("a", encoding="utf-8") as f:
                f.write(json.dumps(found) + "\n")
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_task_store.py -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/clawbot/task_store.py tests/test_task_store.py
git commit -m "feat: TaskStore — JSONL per-agent task queue with create/read/complete/fail"
```

---

### Task 3.2: Workers Read Task Queue Before Each Cycle

**Files:**
- Modify: `src/clawbot/scheduler.py:_worker_agent_loop()`

- [ ] **Step 1: Update `_worker_agent_loop` to prepend pending tasks to the worker prompt**

```python
async def _worker_agent_loop(self, spec: AgentSpec) -> None:
    soul_path = self._resolve_soul_path(spec)
    task_store = getattr(self, "_task_store", None)
    while True:
        if not soul_path.exists():
            logger.info("Worker %s SOUL.md missing — loop ending", spec.agent_id)
            return
        soul = soul_path.read_text(encoding="utf-8")
        interval = (
            EXECUTIVE_SKELETON_INTERVAL_S
            if _is_skeleton_crew_hour()
            else spec.call_interval_s
        )

        # Build task context if store is wired
        task_context = ""
        if task_store is not None:
            tasks = task_store.read_tasks(spec.agent_id)
            if tasks:
                task_lines = "\n".join(
                    f"- [{t['task_id'][:8]}] {t['title']}: {t['description'][:200]}"
                    for t in tasks[:5]  # cap at 5 to control prompt length
                )
                task_context = f"\n\nYour pending tasks:\n{task_lines}"

        try:
            tier = "executive" if spec.agent_id in EXECUTIVE_IDS else "worker"
            response = await self._pool.complete(
                [
                    {"role": "system", "content": soul},
                    {"role": "user", "content": (
                        f"What is your next action? Report result as JSON.{task_context}"
                    )},
                ],
                tier=tier,
            )
            await self._bus.publish(
                f"agent.{spec.agent_id}.output",
                {"result": response, "agent_id": spec.agent_id},
            )
        except Exception as exc:
            logger.warning("Worker %s cycle failed: %s", spec.agent_id, exc)
        await asyncio.sleep(interval)
```

- [ ] **Step 2: Run tests**

```
pytest tests/test_scheduler.py -v
```

Expected: all PASS

- [ ] **Step 3: Commit**

```bash
git add src/clawbot/scheduler.py
git commit -m "feat: workers read TaskStore before each cycle — bidirectional task visibility"
```

---

## Phase 4 — Self-Scheduling with Anti-Windup

### Task 4.1: Parse next_wakeup_s + Budget Circuit Breaker

**Files:**
- Modify: `src/clawbot/scheduler.py`
- Test: `tests/test_scheduler_selfschedule.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_scheduler_selfschedule.py`:

```python
from clawbot.scheduler import _clamp_wakeup


def test_clamp_wakeup_respects_floor():
    assert _clamp_wakeup(10) == 60


def test_clamp_wakeup_respects_ceiling():
    assert _clamp_wakeup(9999) == 1800


def test_clamp_wakeup_passes_valid_value():
    assert _clamp_wakeup(300) == 300


def test_clamp_wakeup_anti_windup_at_70pct():
    """When budget is at 70%+ of daily limit, minimum wakeup is 1800s."""
    assert _clamp_wakeup(60, budget_fraction=0.70) == 1800
    assert _clamp_wakeup(300, budget_fraction=0.85) == 1800
    assert _clamp_wakeup(300, budget_fraction=0.69) == 300
```

- [ ] **Step 2: Run to verify they fail**

```
pytest tests/test_scheduler_selfschedule.py::test_clamp_wakeup_respects_floor -v
```

Expected: FAIL — `cannot import name '_clamp_wakeup' from 'clawbot.scheduler'`

- [ ] **Step 3: Add `_clamp_wakeup` and constants to `scheduler.py`**

```python
# Add constants (near top with other interval constants):
_WAKEUP_FLOOR_S = 60
_WAKEUP_CEILING_S = 1800
_BUDGET_ANTIWINDUP_THRESHOLD = 0.70  # fraction of daily spend limit

def _clamp_wakeup(wakeup_s: int | float, budget_fraction: float = 0.0) -> int:
    """Clamp agent-declared wakeup interval within safe bounds.

    Anti-windup: if daily budget consumption >= 70%, force maximum interval
    to slow the system before the kill switch fires.
    """
    if budget_fraction >= _BUDGET_ANTIWINDUP_THRESHOLD:
        return _WAKEUP_CEILING_S
    return max(_WAKEUP_FLOOR_S, min(_WAKEUP_CEILING_S, int(wakeup_s)))
```

- [ ] **Step 4: Wire into executive loops**

In `_run_executive_cycle()` and `_run_lieutenant_cycle()`, after parsing the JSON response, extract `next_wakeup_s` and use it for the loop sleep:

Since the executive loops (`_executive_loop` and `_lieutenant_loop`) currently sleep for a fixed interval, we need to pass the wakeup back. The cleanest approach is to store it on the scheduler instance per-agent:

```python
# Add to Scheduler.__init__:
self._next_wakeup_s: dict[str, int] = {}  # agent_id → next sleep interval

# In _run_executive_cycle(), after successful response parse:
try:
    data = _extract_json(response)
    wakeup = int(data.get("next_wakeup_s", EXECUTIVE_PEAK_INTERVAL_S))
    self._next_wakeup_s["ceo"] = _clamp_wakeup(wakeup)
except Exception:
    pass  # malformed JSON — keep default interval

# In _executive_loop(), replace fixed sleep with:
interval = self._next_wakeup_s.get(
    "ceo",
    EXECUTIVE_SKELETON_INTERVAL_S if _is_skeleton_crew_hour() else EXECUTIVE_PEAK_INTERVAL_S,
)
await asyncio.sleep(interval)

# Same pattern in _lieutenant_loop() using agent_id as key.
```

- [ ] **Step 5: Add budget fraction calculation for anti-windup**

```python
# In _executive_loop and _lieutenant_loop, compute budget fraction before sleep:
async def _get_budget_fraction(self) -> float:
    """Return fraction of daily spend limit already consumed. Returns 0.0 on error."""
    try:
        spent = await self._monitor.current_spend_usd()
        from clawbot.config import settings
        return spent / settings.max_daily_spend_usd
    except Exception:
        return 0.0
```

Then in the loop:
```python
budget_frac = await self._get_budget_fraction()
interval = _clamp_wakeup(
    self._next_wakeup_s.get("ceo", EXECUTIVE_PEAK_INTERVAL_S),
    budget_fraction=budget_frac,
)
await asyncio.sleep(interval)
```

Note: Check `src/clawbot/monitor.py` to verify `current_spend_usd()` method exists. If it doesn't, add it. If the Monitor doesn't track cumulative spend, `budget_fraction` will remain 0.0 (anti-windup disabled but safe — it just won't kick in).

- [ ] **Step 6: Run tests**

```
pytest tests/test_scheduler_selfschedule.py -v
```

Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add src/clawbot/scheduler.py tests/test_scheduler_selfschedule.py
git commit -m "feat: self-scheduling — agents declare next_wakeup_s (60-1800s) with 70% budget anti-windup"
```

---

## Phase 5 — Agent Inboxes

### Task 5.1: Per-Agent Inbox Streams with maxlen Guard

**Files:**
- Modify: `src/clawbot/scheduler.py`
- Test: append to `tests/test_scheduler_selfschedule.py`

The inbox system enables agents to receive messages from other agents (via DirectiveRouter's `message` action) and from the operator. Workers read their inbox before each cycle and include messages in their prompt.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_scheduler_selfschedule.py`:

```python
async def test_worker_prompt_includes_inbox_messages():
    """Messages published to inbox.{agent_id} must appear in the worker's prompt."""
    from clawbot.scheduler import Scheduler
    from clawbot.agent_registry import AgentSpec

    prompts_seen = []

    pool = MagicMock()
    async def capture_prompt(messages, tier="worker"):
        prompts_seen.append(messages)
        return '{"action": "wait"}'
    pool.complete = capture_prompt

    bus = MagicMock()
    bus.publish = AsyncMock()
    # Inbox has one message
    bus.read_and_ack = AsyncMock(return_value=[{
        "from": "ceo", "message": "prioritise the ISA guide", "chain_id": "abc",
    }])

    s = Scheduler(pool=pool, bus=bus, monitor=MagicMock())
    s._metrics_dir = MagicMock()
    s._next_wakeup_s = {}

    spec = AgentSpec(
        agent_id="worker-001", role="Researcher", supervisor="ceo",
        soul_path="agents/worker-001/SOUL.md", status="active",
        created_at="2026-01-01T00:00:00Z", call_interval_s=600,
    )
    soul_mock = MagicMock()
    soul_mock.exists.return_value = True
    soul_mock.read_text.return_value = "# SOUL"

    with patch.object(s, "_resolve_soul_path", return_value=soul_mock):
        # Run one iteration (cancel after first sleep)
        try:
            await asyncio.wait_for(s._worker_agent_loop(spec), timeout=0.5)
        except asyncio.TimeoutError:
            pass

    assert len(prompts_seen) >= 1
    user_msg = prompts_seen[0][1]["content"]
    assert "prioritise the ISA guide" in user_msg
```

- [ ] **Step 2: Run to verify it fails**

```
pytest tests/test_scheduler_selfschedule.py::test_worker_prompt_includes_inbox_messages -v
```

Expected: FAIL — worker loop doesn't read inbox.

- [ ] **Step 3: Update `_worker_agent_loop` to read inbox**

```python
# In _worker_agent_loop, before the pool.complete call, add inbox reading:
inbox_context = ""
try:
    inbox_msgs = await self._bus.read_and_ack(
        f"inbox.{spec.agent_id}",
        f"worker-{spec.agent_id}",
        count=5,
        block_ms=100,
    )
    if inbox_msgs:
        lines = "\n".join(
            f"- From {m.get('from', 'unknown')}: {m.get('message', '')[:200]}"
            for m in inbox_msgs
        )
        inbox_context = f"\n\nInbox messages:\n{lines}"
except Exception:
    pass  # inbox read failure must not block the worker cycle
```

Also subscribe to each worker's inbox during `_dynamic_agent_sync_loop`:

```python
# In _sync_dynamic_agents, when starting a new worker task, also subscribe to its inbox:
await self._bus.subscribe(f"inbox.{spec.agent_id}")
```

The `bus.publish` in DirectiveRouter's `_handle_message_action` already sets `maxlen` via the existing `bus.publish()` which calls `xadd` with `maxlen=10_000`. Inbox streams are limited to 1,000 messages to prevent OOM on inactive agents:

```python
# In directive_router.py, _handle_message_action — use a lower maxlen for inboxes:
# Change the bus.publish call to use a direct xadd with maxlen=1000, or
# add a publish_inbox helper to MessageBus.

# In bus.py, add:
async def publish_inbox(self, agent_id: str, payload: dict) -> str:
    """Publish to a per-agent inbox stream with a tighter maxlen cap."""
    entry = {
        "payload": __import__("json").dumps(payload),
        "ts": __import__("datetime").datetime.now(__import__("datetime").UTC).isoformat(),
    }
    msg_id: str = await self._r.xadd(
        _stream(f"inbox.{agent_id}"), entry, maxlen=1_000, approximate=True,
    )
    return msg_id
```

Then in `directive_router.py._handle_message_action`, use `bus.publish_inbox(target, {...})`.

- [ ] **Step 4: Run tests**

```
pytest tests/test_scheduler_selfschedule.py -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/clawbot/scheduler.py src/clawbot/bus.py src/clawbot/directive_router.py tests/test_scheduler_selfschedule.py
git commit -m "feat: per-agent inbox streams — workers read messages before each cycle"
```

---

## Phase 6 — Web Research Tool

### Task 6.1: HTTP Web Researcher + DirectiveRouter Handler

**Files:**
- Create: `src/clawbot/web_researcher.py`
- Modify: `src/clawbot/directive_router.py` (add `web_research` handler)
- Test: `tests/test_directive_router.py` (extend)

Note: Using httpx directly, not Playwright. Playwright adds 20MB overhead and gets IP-banned on research sites. httpx is already a dependency. For pages that require JS rendering, the agent should escalate to the operator for manual research.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_directive_router.py`:

```python
async def test_web_research_handler_writes_to_brain():
    from clawbot.directive_router import DirectiveRouter
    import httpx

    chain_id = str(uuid.uuid4())
    msg = make_directive_msg("web_research")
    msg["response"] = json.dumps({
        "action": "web_research",
        "url": "https://example.com/uk-isa-rules",
        "query": "ISA contribution limits 2026",
    })
    bus = make_bus({"ceo.directive": [msg]})

    brain = MagicMock()
    brain.write = AsyncMock(return_value=1)

    causal_store = MagicMock()
    causal_store.record_event = AsyncMock(return_value=str(uuid.uuid4()))

    router = DirectiveRouter(
        bus=bus, causal_store=causal_store, registry=MagicMock(),
        agent_factory=MagicMock(), task_store=MagicMock(),
        metrics_dir=MagicMock(), brain=brain,
    )

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "<html><body><p>ISA limit is £20,000 for 2026</p></body></html>"

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
        mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
        mock_client.return_value.get = AsyncMock(return_value=mock_response)
        await router._poll_once()

    brain.write.assert_called_once()
    call_args = brain.write.call_args
    assert "ISA" in call_args.args[0] or "ISA" in str(call_args.kwargs)
```

- [ ] **Step 2: Run to verify it fails**

```
pytest tests/test_directive_router.py::test_web_research_handler_writes_to_brain -v
```

Expected: FAIL — `web_research` not in `_get_handler` dispatch table; `DirectiveRouter.__init__` has no `brain` param.

- [ ] **Step 3: Create `src/clawbot/web_researcher.py`**

```python
"""
Lightweight HTTP research tool for agent-directed web fetches.

Uses httpx (already a dependency). Does NOT use Playwright — JS-heavy pages
should trigger an operator escalation instead. Returns cleaned plaintext
suitable for brain storage and LLM summarization.
"""
from __future__ import annotations

import logging
import re

import httpx

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT_S = 15.0
_MAX_CONTENT_CHARS = 8_000
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ClawbotResearch/0.1; +research-bot)",
    "Accept": "text/html,text/plain,*/*",
}


def _strip_html(html: str) -> str:
    """Crude HTML → plaintext. Good enough for factual pages; not for complex SPAs."""
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:_MAX_CONTENT_CHARS]


async def fetch_and_extract(url: str) -> str:
    """Fetch URL and return extracted plaintext. Raises on HTTP error or timeout."""
    async with httpx.AsyncClient(
        timeout=_HTTP_TIMEOUT_S, headers=_HEADERS, follow_redirects=True,
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    if "html" in content_type:
        return _strip_html(response.text)
    return response.text[:_MAX_CONTENT_CHARS]
```

- [ ] **Step 4: Update `directive_router.py`**

Add `brain` param to `__init__`:

```python
def __init__(
    self,
    bus: "MessageBus",
    causal_store: "CausalStore",
    registry: "AgentRegistry",
    agent_factory: "AgentFactory",
    task_store: "TaskStore",
    metrics_dir: Path,
    brain: "CompanyBrain | None" = None,
) -> None:
    ...
    self._brain = brain
```

Add to `_get_handler`:
```python
"web_research": self._handle_web_research,
```

Add handler:
```python
async def _handle_web_research(self, data: dict, chain_id: str, from_agent: str) -> None:
    from clawbot.web_researcher import fetch_and_extract
    url = str(data.get("url", ""))[:500]
    query = str(data.get("query", "web research"))[:200]
    if not url:
        raise ValueError("web_research action missing url")
    try:
        content = await fetch_and_extract(url)
    except Exception as exc:
        raise RuntimeError(f"Web fetch failed for {url}: {exc}") from exc
    if self._brain is not None:
        await self._brain.write(
            f"Web research [{query}] from {url}:\n{content}",
            category="research",
            metadata={"url": url, "query": query, "chain_id": chain_id},
        )
    logger.info("Web research complete: %s (%d chars)", url, len(content))
```

- [ ] **Step 5: Run tests**

```
pytest tests/test_directive_router.py -v
```

Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add src/clawbot/web_researcher.py src/clawbot/directive_router.py tests/test_directive_router.py
git commit -m "feat: web_research action — httpx fetch → brain storage with CAG attribution"
```

---

## Phase 7 — Lateral Thinker

### Task 7.1: Weekly Cross-Signal Synthesis

**Files:**
- Create: `src/clawbot/lateral_thinker.py`
- Modify: `src/clawbot/scheduler.py` (add lateral thinker loop)
- Test: `tests/test_lateral_thinker.py`

The lateral thinker reads market signals from the last 14 days, synthesises cross-signal patterns ("what opportunities cluster together?"), and writes a synthesis to the brain. The temporal coherence gate rejects signals older than 14 days because stale data biases the synthesis toward expired opportunities.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_lateral_thinker.py
import time
import pytest
from unittest.mock import AsyncMock, MagicMock


async def test_lateral_thinker_skips_when_too_few_signals():
    """Below MIN_SIGNALS threshold, synthesis must be skipped."""
    from clawbot.lateral_thinker import LateralThinker, MIN_SIGNALS

    brain = MagicMock()
    brain.search = AsyncMock(return_value=[])  # 0 signals
    brain.write = AsyncMock()

    pool = MagicMock()
    pool.complete = AsyncMock()

    thinker = LateralThinker(pool=pool, brain=brain)
    await thinker.synthesise()

    pool.complete.assert_not_called()
    brain.write.assert_not_called()


async def test_lateral_thinker_skips_stale_signals():
    """Signals older than FRESHNESS_DAYS must be excluded from synthesis."""
    from clawbot.lateral_thinker import LateralThinker, FRESHNESS_DAYS

    stale_ts = time.time() - (FRESHNESS_DAYS + 1) * 86400

    class FakeEntry:
        def __init__(self):
            self.content = "old opportunity"
            self.metadata = {"ts": stale_ts}
            self.id = 1

    brain = MagicMock()
    brain.search = AsyncMock(return_value=[FakeEntry()] * 5)
    brain.write = AsyncMock()

    pool = MagicMock()
    pool.complete = AsyncMock()

    thinker = LateralThinker(pool=pool, brain=brain)
    await thinker.synthesise()

    # All signals were stale → synthesis skipped
    pool.complete.assert_not_called()


async def test_lateral_thinker_synthesises_fresh_signals():
    """With MIN_SIGNALS fresh signals, synthesis must be triggered and stored."""
    from clawbot.lateral_thinker import LateralThinker, MIN_SIGNALS

    fresh_ts = time.time() - 86400  # 1 day ago

    class FakeEntry:
        def __init__(self, title: str):
            self.content = f"Opportunity: {title}"
            self.metadata = {"ts": fresh_ts}
            self.id = hash(title)

    brain = MagicMock()
    brain.search = AsyncMock(return_value=[
        FakeEntry(f"signal-{i}") for i in range(MIN_SIGNALS)
    ])
    brain.write = AsyncMock(return_value=99)

    pool = MagicMock()
    pool.complete = AsyncMock(return_value="Cross-signal insight: multiple opportunities in UK tax space.")

    thinker = LateralThinker(pool=pool, brain=brain)
    await thinker.synthesise()

    pool.complete.assert_called_once()
    brain.write.assert_called_once()
    call_args = brain.write.call_args
    assert call_args.kwargs.get("category") == "lateral_thought"
```

- [ ] **Step 2: Run to verify they fail**

```
pytest tests/test_lateral_thinker.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'clawbot.lateral_thinker'`

- [ ] **Step 3: Create `src/clawbot/lateral_thinker.py`**

```python
"""
Lateral thinker — weekly cross-signal synthesis.

Reads market_signal entries from the brain, filters to the freshness window,
and asks an LLM to identify cross-signal patterns: what themes cluster? What
timing windows align? What products could serve multiple signals at once?

The temporal coherence gate (FRESHNESS_DAYS=14) prevents stale signals from
biasing the synthesis. MIN_SIGNALS=3 prevents synthesis on noise (one signal
is a data point; three is a pattern).

Output is stored in brain as category="lateral_thought" for the CEO/meta-
evaluator to read during their next cycle.
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from clawbot.company_brain import CompanyBrain
    from clawbot.llm_pool import LLMPool

logger = logging.getLogger(__name__)

MIN_SIGNALS = 3
FRESHNESS_DAYS = 14
_SYNTHESIS_PROMPT = """\
You are a lateral thinking analyst for a UK digital products business.

Below are {n} market signals observed in the past {days} days:

{signals}

Your task: identify cross-signal themes and synthesis insights that no single
signal reveals alone. Look for:
1. Clusters: multiple signals pointing at the same underlying need
2. Timing alignment: signals that suggest the same window of opportunity
3. Leverage: one product that could address multiple signals simultaneously
4. Contradictions: signals that suggest the market is split or confused

Output a concise synthesis (200-400 words) with 2-4 concrete product ideas
that emerge from the cross-signal view. Be specific — name the product, the
audience, and why this window exists now.
"""


class LateralThinker:
    def __init__(
        self,
        pool: "LLMPool",
        brain: "CompanyBrain",
    ) -> None:
        self._pool = pool
        self._brain = brain

    async def synthesise(self) -> str | None:
        """Read fresh market signals, synthesise cross-signal insights, write to brain.

        Returns the synthesis text, or None if conditions for synthesis are not met.
        """
        try:
            entries = await self._brain.search(
                query="market opportunity UK digital product",
                k=20,
                category="market_signal",
            )
        except Exception as exc:
            logger.warning("LateralThinker: brain search failed: %s", exc)
            return None

        cutoff = time.time() - FRESHNESS_DAYS * 86_400
        fresh = [
            e for e in entries
            if float(e.metadata.get("ts", time.time())) >= cutoff
        ]

        if len(fresh) < MIN_SIGNALS:
            logger.info(
                "LateralThinker: only %d fresh signals (need %d) — synthesis skipped",
                len(fresh), MIN_SIGNALS,
            )
            return None

        signal_text = "\n".join(
            f"[{i+1}] {e.content[:300]}"
            for i, e in enumerate(fresh[:15])  # cap to control prompt size
        )
        prompt = _SYNTHESIS_PROMPT.format(
            n=len(fresh[:15]),
            days=FRESHNESS_DAYS,
            signals=signal_text,
        )

        try:
            synthesis = await self._pool.complete(
                [
                    {"role": "system", "content": "You are a lateral thinking analyst."},
                    {"role": "user", "content": prompt},
                ],
                tier="executive",
            )
        except Exception as exc:
            logger.error("LateralThinker: LLM call failed: %s", exc)
            return None

        try:
            await self._brain.write(
                synthesis,
                category="lateral_thought",
                metadata={"signal_count": len(fresh), "ts": time.time()},
            )
        except Exception as exc:
            logger.warning("LateralThinker: brain write failed: %s", exc)

        logger.info("LateralThinker: synthesis complete (%d chars)", len(synthesis))
        return synthesis
```

- [ ] **Step 4: Add the `_lateral_thinker_loop` to `scheduler.py`**

Add constant:
```python
LATERAL_THINKER_INTERVAL_S = 7 * 86_400  # weekly
```

Add loop method to `Scheduler`:
```python
async def _lateral_thinker_loop(self) -> None:
    """Weekly cross-signal synthesis. Skipped if brain not wired."""
    if self._brain is None:
        return
    from clawbot.lateral_thinker import LateralThinker
    thinker = LateralThinker(pool=self._pool, brain=self._brain)
    while True:
        await asyncio.sleep(LATERAL_THINKER_INTERVAL_S)
        try:
            result = await thinker.synthesise()
            if result:
                logger.info("Lateral thinker synthesis stored (%d chars)", len(result))
        except Exception as exc:
            logger.error("Lateral thinker cycle failed: %s", exc)
```

Add to `run_forever()`:
```python
if self._brain is not None:
    tasks.append(asyncio.create_task(
        self._lateral_thinker_loop(), name="lateral-thinker"
    ))
```

- [ ] **Step 5: Run tests**

```
pytest tests/test_lateral_thinker.py -v
```

Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add src/clawbot/lateral_thinker.py src/clawbot/scheduler.py tests/test_lateral_thinker.py
git commit -m "feat: lateral thinker — weekly cross-signal synthesis with 14-day freshness gate"
```

---

## Phase 8 — Operator Product Confirmation Loop

### Task 8.1: Parse Gumroad URL from Operator Reply → Close Chain

**Files:**
- Modify: `src/clawbot/scheduler.py:_operator_reply_loop()`
- Test: append to `tests/test_scheduler_selfschedule.py`

When `publish_product` fires, the operator receives a Telegram escalation with instructions to create the product on Gumroad and reply with format: `PRODUCT_URL:<url> CHAIN:<chain_id>`. The reply loop must parse this, register the product in `CausalStore`, and close any matching open chains when Gumroad sales are detected.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_scheduler_selfschedule.py`:

```python
from clawbot.scheduler import _parse_product_reply


def test_parse_product_reply_extracts_url_and_chain():
    url, chain_id = _parse_product_reply(
        "PRODUCT_URL:https://gumroad.com/l/uk-isa-guide CHAIN:abc123-456"
    )
    assert url == "https://gumroad.com/l/uk-isa-guide"
    assert chain_id == "abc123-456"


def test_parse_product_reply_returns_none_for_missing_url():
    assert _parse_product_reply("no url here") == (None, None)


def test_parse_product_reply_handles_extra_whitespace():
    url, chain_id = _parse_product_reply(
        "  PRODUCT_URL: https://gumroad.com/l/test   CHAIN: chain-xyz  "
    )
    assert url == "https://gumroad.com/l/test"
    assert chain_id == "chain-xyz"
```

- [ ] **Step 2: Run to verify they fail**

```
pytest tests/test_scheduler_selfschedule.py::test_parse_product_reply_extracts_url_and_chain -v
```

Expected: FAIL — `cannot import name '_parse_product_reply' from 'clawbot.scheduler'`

- [ ] **Step 3: Add `_parse_product_reply` to `scheduler.py`**

```python
import re as _re

def _parse_product_reply(reply: str) -> tuple[str | None, str | None]:
    """Extract Gumroad product URL and chain_id from an operator reply string.

    Expected format: "PRODUCT_URL:<url> CHAIN:<chain_id>"
    Returns (url, chain_id) or (None, None) if format not matched.
    """
    url_match = _re.search(r"PRODUCT_URL:\s*(https?://\S+)", reply)
    chain_match = _re.search(r"CHAIN:\s*(\S+)", reply)
    if not url_match or not chain_match:
        return None, None
    url = url_match.group(1).strip()
    chain_id = chain_match.group(1).strip()
    return url, chain_id
```

- [ ] **Step 4: Update `_operator_reply_loop` to handle product confirmations**

Find `_operator_reply_loop` in scheduler.py and add product confirmation handling:

```python
async def _operator_reply_loop(self) -> None:
    """Poll escalation_replies.jsonl and republish to operator.reply bus topic.
    Also handles PRODUCT_URL confirmations from publish_product escalations."""
    ...  # existing logic preserved
    # After republishing to bus, add:
    reply_text = msg.get("reply", "")
    if "PRODUCT_URL:" in reply_text and self._causal_store is not None:
        url, chain_id = _parse_product_reply(reply_text)
        if url and chain_id:
            product_id = _extract_gumroad_product_id(url)
            if product_id:
                try:
                    await self._causal_store.register_product(
                        gumroad_product_id=product_id,
                        chain_id=chain_id,
                        product_title=url,
                    )
                    logger.info(
                        "Registered product %s → chain %s", product_id, chain_id,
                    )
                except Exception as exc:
                    logger.error("Failed to register product: %s", exc)
```

Add the URL parser:

```python
def _extract_gumroad_product_id(url: str) -> str | None:
    """Extract Gumroad product ID from a product URL.

    Gumroad URLs: https://gumroad.com/l/<product_id> or https://<seller>.gumroad.com/l/<id>
    """
    match = _re.search(r"/l/([a-zA-Z0-9_-]+)", url)
    return match.group(1) if match else None
```

- [ ] **Step 5: Add Gumroad sale → chain closure to `_fitness_writer_loop`**

When the fitness writer runs, it also checks for Gumroad sales that match registered products and closes any open chains:

```python
async def _fitness_writer_loop(self) -> None:
    while True:
        await asyncio.sleep(FITNESS_WRITER_INTERVAL_S)
        try:
            from clawbot.fitness_writer import refresh_all_fitness
            metrics = await self._load_metrics()
            revenue = float(metrics.get("revenue_7d_gbp", 0.0))
            results = await refresh_all_fitness(
                self._metrics_dir, revenue,
                causal_store=getattr(self, "_causal_store", None),
            )
            logger.info("Fitness refreshed for %d agents", len(results))

            # Close chains for any Gumroad sales matched to registered products
            if self._causal_store is not None:
                await self._attribute_recent_sales()
        except Exception as exc:
            logger.error("Fitness writer cycle failed: %s", exc)

async def _attribute_recent_sales(self) -> None:
    """Check Gumroad for recent sales; close chains for registered products."""
    if not settings.gumroad_api_key:
        return
    try:
        from clawbot.gumroad import GumroadClient
        client = GumroadClient(api_key=settings.gumroad_api_key)
        sales = await client.sales()
        product_ids = list({s.get("product_id", "") for s in sales if s.get("product_id")})
        if not product_ids:
            return
        pairs = await self._causal_store.unattributed_sale_products(product_ids)
        for product_id, chain_id in pairs:
            sale_total = sum(
                float(s.get("price", 0)) / 100
                for s in sales
                if s.get("product_id") == product_id
            )
            if sale_total > 0:
                await self._causal_store.close_chain(chain_id, sale_total)
                logger.info(
                    "Attributed £%.2f to chain %s (product %s)",
                    sale_total, chain_id, product_id,
                )
    except Exception as exc:
        logger.warning("Sale attribution failed (non-fatal): %s", exc)
```

Note: Check `gumroad.py` to verify `sales()` returns a list of dicts with `product_id` and `price` keys. If the field names differ, update accordingly.

- [ ] **Step 6: Run tests**

```
pytest tests/test_scheduler_selfschedule.py -v
```

Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add src/clawbot/scheduler.py tests/test_scheduler_selfschedule.py
git commit -m "feat: operator product confirmation loop — PRODUCT_URL reply registers chain; fitness writer closes chains on sale"
```

---

## Phase 9 — Main Wiring

### Task 9.1: Wire CausalStore and TaskStore into main.py

**Files:**
- Modify: `src/clawbot/main.py`
- Modify: `src/clawbot/scheduler.py` (constructor signature already updated in Task 2.3)

- [ ] **Step 1: Update `main.py`**

```python
# In main.py, add imports:
from clawbot.causal_store import CausalStore
from clawbot.task_store import TaskStore

# In the main() function, after db.init_schema():
causal_store = CausalStore(pool=db.pool)
task_store = TaskStore(tasks_dir=METRICS_DIR / "tasks")

# Update Scheduler construction:
scheduler = Scheduler(
    pool=pool, bus=bus, monitor=monitor,
    registry=registry, brain=brain, homeostasis=homeostasis,
    causal_store=causal_store, task_store=task_store,
)

# Add new bus topics to the subscription list:
topics = [
    "ceo.directive", "cfo.directive", "cmo.directive",
    "coo.directive", "cto.directive",
    "board.resolution", "coo.task", "cmo.campaign",
    "code.change_request", "operator.escalation", "operator.reply",
    "operator.message",
    "ceo.cycle_start", "cfo.cycle_start", "cmo.cycle_start",
    "coo.cycle_start", "cto.cycle_start",
    "brain.recall", "brain.write",
]
```

Import `METRICS_DIR` from scheduler:
```python
from clawbot.scheduler import AGENTS_DIR, METRICS_DIR, Scheduler
```

- [ ] **Step 2: Also wire `brain` into DirectiveRouter in Scheduler**

In `run_forever()` where the DirectiveRouter is constructed, pass `brain`:
```python
router = DirectiveRouter(
    bus=self._bus,
    causal_store=self._causal_store,
    registry=self._registry,
    agent_factory=factory,
    task_store=task_store,
    metrics_dir=self._metrics_dir,
    brain=self._brain,
)
```

- [ ] **Step 3: Run the full test suite**

```
pytest tests/ -v --tb=short
```

Expected: all PASS

- [ ] **Step 4: Final commit**

```bash
git add src/clawbot/main.py src/clawbot/scheduler.py
git commit -m "feat: wire CausalStore + TaskStore into main.py — living system fully connected"
```

---

## Self-Review Checklist

### Spec Coverage
| Requirement | Task |
|---|---|
| CAG tables in Postgres | Task 0.1 |
| CausalStore (record/close/attribute) | Task 0.2 |
| OpportunityScanner generates chain_id | Task 0.3 |
| Distributed fitness (per-agent attributed revenue) | Tasks 1.1, 1.2 |
| DirectiveRouter with at-least-once delivery | Task 2.2 |
| hire/fire/assign_task/publish_product/message handlers | Task 2.2 |
| chain_id in all directives | Task 2.3 |
| TaskStore (create/read/complete/fail) | Task 3.1 |
| Workers read task queue | Task 3.2 |
| Self-scheduling (next_wakeup_s + anti-windup) | Task 4.1 |
| Per-agent inbox streams (maxlen guard) | Task 5.1 |
| Web research tool (httpx → brain) | Task 6.1 |
| Lateral thinker (14-day freshness gate, MIN_SIGNALS=3) | Task 7.1 |
| Operator product confirmation (PRODUCT_URL parsing) | Task 8.1 |
| Gumroad sale → chain closure | Task 8.1 |
| Main.py wiring | Task 9.1 |

### Placeholder Scan
- No TBDs, no "implement later" steps
- Task 0.3 Step 3 notes "check company_brain.py for metadata param" — this is a verify step, not a deferral; the code shows how to add it if missing
- Task 2.3 Step 3 note to check `_extract_json` uses — actionable, not deferred
- Task 4.1 Step 5 note to check `Monitor.current_spend_usd()` — add if missing, fallback is safe

### Type Consistency
- `CausalStore.record_event()` → `str` (event_id UUID)
- `CausalStore.close_chain()` → `None`
- `CausalStore.attributed_revenue_7d()` → `float`
- `CausalStore.attribution_rate()` → `float`
- `CausalStore.register_product()` → `None`
- `CausalStore.product_chain_id()` → `str | None`
- `CausalStore.unattributed_sale_products()` → `list[tuple[str, str]]`
- `TaskStore.create_task()` → `str` (task_id)
- `TaskStore.read_tasks()` → `list[dict]`
- `LateralThinker.synthesise()` → `str | None`
- `DirectiveRouter._poll_once()` → `None`
- `_parse_product_reply()` → `tuple[str | None, str | None]`
- `_clamp_wakeup()` → `int`
- `refresh_all_fitness()` is now `async` — all callers use `await`
