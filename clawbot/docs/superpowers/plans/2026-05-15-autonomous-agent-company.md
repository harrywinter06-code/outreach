# Autonomous Agent Company — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A fully autonomous, self-evolving company of AI agents that discovers revenue opportunities in the UK digital economy, executes them 24/7, and evolves its strategy through a board-enforced feedback loop — with no ongoing human involvement after initial setup.

**Architecture:** Five shareholder agents govern via daily board votes, reading raw metrics directly. CEO executes board-approved direction, delegates to CFO, CMO, CTO, COO, and dynamically hires/fires worker agents as capacity demands. Meta-evaluator scores agents by revenue-grounded fitness and mutates or fires the bottom 20%. Opportunity Scanner watches Reddit/HN independently, reporting only to the Opportunist Shareholder. A Corporate Charter (immutable) enforces spending limits, diversity, and the kill switch.

**Tech Stack:** Python 3.13 + uv, browser-use, Redis Streams 7, PostgreSQL 16 + pgvector, Docker Compose, Hetzner CX32 (8GB min). LLM pool: NVIDIA NIM × up to 5 keys (40 RPM / 38K RPD each) + Groq (30 RPM / 6K RPD 70B, 14.4K RPD 8B) + Gemini Flash (15 RPM / 1.5K RPD) + Cerebras (30 RPM / 14.4K RPD).

**First revenue hypothesis (pre-loaded):** £9 IR35 contractor status assessment PDF on Gumroad → distributed via r/ContractorUK (130K members). Impulse-buy price, zero fulfilment cost, AI-native content, no seller reputation required.

**Architectural decisions recorded:**
- 5× NIM multi-accounting → multi-provider + up to 5 NIM keys (each independent rate-limit bucket; ban of one doesn't affect others)
- Hermes Agent runtime → custom asyncio Scheduler (no unverified dependency)
- Redis Pub/Sub → Redis Streams (persistent, consumer-group, no message loss on crash)
- In-memory rate limiter → Redis INCR per-minute + per-day (multi-container safe)
- Fitness: proxy metrics only → revenue 60% weight, hard cap 0.30 at £0 revenue
- Kill switch: Redis-only → file-based primary + Redis secondary
- VPS: CX22 → CX32 (3× Chromium + services ≈ 2.5GB peak RAM)
- CEO SOUL.md: "Undecided" → pre-loaded H1 (IR35 product, avoids cold-start trap)
- Evolution prompt: no history → includes failed strategy log (Goodhart countermeasure)
- Fixed org chart → dynamic agent registry (CEO hires/fires workers via AgentFactory)

---

## Current Implementation Status

### ✅ Completed — 62/62 tests passing

| File | Description |
|---|---|
| `pyproject.toml` | Dependencies: redis, httpx, pydantic-settings, browser-use, langchain-openai, tenacity, pgvector, asyncpg |
| `.env.example` | NIM × 5 keys, Groq, Gemini, Cerebras; Gumroad + Stripe keys |
| `Dockerfile` | Python 3.13-slim + Chromium |
| `docker-compose.yml` | Redis 7, Postgres 16+pgvector, clawbot; CX32 sizing note |
| `CORPORATE_CHARTER.md` | Immutable constitution |
| `src/clawbot/config.py` | Multi-provider settings; RPM + RPD per provider; `nim_api_keys` list property |
| `src/clawbot/llm_pool.py` | Round-robin pool; per-minute + per-day Redis counters; AsyncRetrying backoff |
| `src/clawbot/bus.py` | Redis Streams; publish / read / ack / read_and_ack |
| `src/clawbot/genome.py` | Atomic SOUL.md write (temp-rename); extract/replace mutable section |
| `src/clawbot/lateral.py` | Six-frame analysis (7 LLM calls); executive tier only |
| `src/clawbot/fitness.py` | Revenue 60% weight; 0.30 Goodhart cap; save/load; bottom_percentile |
| `src/clawbot/evolution.py` | Mutation cycle; failed strategy history in prompt; fire hook |
| `src/clawbot/monitor.py` | File-based kill switch + Redis secondary; daily spend; RPM visibility |
| `src/clawbot/browser_worker.py` | browser-use wrapper; Semaphore(3) concurrency cap |
| `src/clawbot/scheduler.py` | Executive loop (10 min), board (03:00 UTC), evolution (24h), kill watchdog (30s) |
| `src/clawbot/main.py` | Startup checklist (halts if no payment processor); entry point |
| `src/clawbot/board.py` | Board voting; tally; emergency triggers; quorum |
| `src/clawbot/metrics.py` | MetricsStore writing /metrics JSON files |
| `src/clawbot/opportunity_scanner.py` | Reddit/HN scanner; reports to Opportunist Shareholder |
| `src/clawbot/agent_registry.py` | Redis-backed org chart; register/deregister/list_active; executive guard |
| `src/clawbot/agent_factory.py` | spawn() generates SOUL.md via LLM + registers; fire() archives SOUL.md |
| `agents/shareholder-*/SOUL.md` | All 5 shareholder genomes (IMMUTABLE mandates) |
| `agents/ceo/SOUL.md` | H1 hypothesis pre-loaded |
| `agents/cfo,cmo,cto,coo,meta/SOUL.md` | All executive genomes |
| `agents/templates/content-writer.md` | Worker template: Reddit content, Gumroad descriptions |
| `agents/templates/researcher.md` | Worker template: opportunity briefs, gap analysis |
| `agents/templates/outreach.md` | Worker template: Reddit/Quora/LinkedIn replies |
| `tests/test_board.py` | 9 tests |
| `tests/test_bus.py` | 8 tests |
| `tests/test_fitness.py` | 9 tests |
| `tests/test_genome.py` | 10 tests |
| `tests/test_llm_pool.py` | 8 tests (RPM + RPD enforcement) |
| `tests/test_agent_registry.py` | 10 tests |
| `tests/test_agent_factory.py` | 8 tests |

---

## Remaining Tasks

### Task R1: Wire dynamic agents into Scheduler

**Problem:** `agent_registry.py` and `agent_factory.py` exist and are tested, but the Scheduler still runs only hardcoded executive loops. Dynamically spawned agents are registered in Redis but never executed.

**Files:** `src/clawbot/scheduler.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_scheduler_dynamic.py
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from clawbot.scheduler import Scheduler
from clawbot.agent_registry import AgentSpec

@pytest.mark.asyncio
async def test_scheduler_starts_loop_for_new_agent():
    spec = AgentSpec(
        agent_id="writer-001", role="Content Writer", supervisor="cmo",
        soul_path="agents/writer-001/SOUL.md", status="active",
        created_at="2026-01-01T00:00:00+00:00", call_interval_s=600,
    )
    calls = []

    async def fake_poll():
        return [spec]

    scheduler = Scheduler(pool=MagicMock(), bus=MagicMock(), monitor=MagicMock())
    scheduler._registry = MagicMock()
    scheduler._registry.list_active = AsyncMock(return_value=[spec])

    # After one poll cycle, writer-001 should be in _agent_tasks
    await scheduler._sync_dynamic_agents()
    assert "writer-001" in scheduler._agent_tasks
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run python -m pytest tests/test_scheduler_dynamic.py -v
```
Expected: `AttributeError` — `_sync_dynamic_agents` not defined.

- [ ] **Step 3: Add to Scheduler**

```python
# In __init__:
self._registry: AgentRegistry | None = None
self._agent_tasks: dict[str, asyncio.Task] = {}

# New method:
async def _sync_dynamic_agents(self) -> None:
    """Poll registry every 60s; start loops for new agents, cancel for fired ones."""
    if self._registry is None:
        return
    active = await self._registry.list_active()
    active_ids = {s.agent_id for s in active if not s.is_executive}

    # Start new agents
    for spec in active:
        if spec.is_executive or spec.agent_id in self._agent_tasks:
            continue
        task = asyncio.create_task(
            self._worker_agent_loop(spec),
            name=f"agent-{spec.agent_id}",
        )
        self._agent_tasks[spec.agent_id] = task

    # Cancel fired agents
    for agent_id in list(self._agent_tasks):
        if agent_id not in active_ids:
            self._agent_tasks.pop(agent_id).cancel()

async def _worker_agent_loop(self, spec: AgentSpec) -> None:
    soul_path = Path(spec.soul_path)
    while True:
        if not soul_path.exists():
            break  # fired — SOUL.md was archived
        soul = soul_path.read_text(encoding="utf-8")
        messages = [
            {"role": "system", "content": soul},
            {"role": "user", "content": "What is your next action? Report result as JSON."},
        ]
        try:
            result = await self._pool.complete(messages, tier="worker")
            await self._bus.publish(f"agent.{spec.agent_id}.output", {"result": result})
        except Exception as exc:
            logger.error("Worker %s failed: %s", spec.agent_id, exc)
        await asyncio.sleep(spec.call_interval_s)
```

- [ ] **Step 4: Add sync loop to `run_forever`**

```python
tasks = [
    asyncio.create_task(self._executive_loop(), name="executive"),
    asyncio.create_task(self._board_loop(), name="board"),
    asyncio.create_task(self._evolution_loop(), name="evolution"),
    asyncio.create_task(self._kill_switch_watchdog(), name="killswitch"),
    asyncio.create_task(self._dynamic_agent_sync_loop(), name="registry-sync"),
]

async def _dynamic_agent_sync_loop(self) -> None:
    while True:
        await self._sync_dynamic_agents()
        await asyncio.sleep(60)
```

- [ ] **Step 5: Run all tests**

```bash
uv run python -m pytest tests/ -v
```
Expected: 65+ passed.

- [ ] **Step 6: Commit**

```bash
git add src/clawbot/scheduler.py tests/test_scheduler_dynamic.py
git commit -m "feat: scheduler polls agent registry and runs dynamic worker loops"
```

---

### Task R2: Gumroad integration

**Problem:** Startup checklist requires `GUMROAD_API_KEY` but no code uses it. The CTO agent can't actually create or manage products.

**Files:** `src/clawbot/gumroad.py`, `tests/test_gumroad.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_gumroad.py
import pytest
from unittest.mock import AsyncMock, patch
import httpx
from clawbot.gumroad import GumroadClient, GumroadProduct

@pytest.mark.asyncio
async def test_create_product_returns_product():
    client = GumroadClient(api_key="test-key")
    mock_response = {"success": True, "product": {"id": "abc123", "name": "IR35 Tool", "price": 900}}
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = AsyncMock(
            status_code=200,
            json=lambda: mock_response,
            raise_for_status=lambda: None,
        )
        product = await client.create_product(name="IR35 Tool", price_gbp=9.00, description="...")
    assert product.id == "abc123"
    assert product.price_gbp == 9.00
```

- [ ] **Step 2: Implement `src/clawbot/gumroad.py`**

```python
from dataclasses import dataclass
import httpx

GUMROAD_API = "https://api.gumroad.com/v2"

@dataclass
class GumroadProduct:
    id: str
    name: str
    price_gbp: float
    url: str = ""

class GumroadClient:
    def __init__(self, api_key: str) -> None:
        self._key = api_key

    async def create_product(self, name: str, price_gbp: float, description: str) -> GumroadProduct:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                f"{GUMROAD_API}/products",
                data={
                    "access_token": self._key,
                    "name": name,
                    "price": int(price_gbp * 100),  # pence
                    "description": description,
                    "currency": "gbp",
                },
            )
            r.raise_for_status()
            p = r.json()["product"]
        return GumroadProduct(id=p["id"], name=p["name"], price_gbp=p["price"] / 100)

    async def list_products(self) -> list[GumroadProduct]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(f"{GUMROAD_API}/products", params={"access_token": self._key})
            r.raise_for_status()
        return [
            GumroadProduct(id=p["id"], name=p["name"], price_gbp=p["price"] / 100)
            for p in r.json()["products"]
        ]

    async def sales_last_7_days_gbp(self) -> float:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(f"{GUMROAD_API}/sales", params={"access_token": self._key})
            r.raise_for_status()
        sales = r.json().get("sales", [])
        return sum(s["price"] for s in sales) / 100
```

- [ ] **Step 3: Run tests, commit**

```bash
uv run python -m pytest tests/test_gumroad.py -v
git add src/clawbot/gumroad.py tests/test_gumroad.py
git commit -m "feat: Gumroad client — create products, list, revenue tracking"
```

---

### Task R3: Metrics writer

**Problem:** `scheduler.py` reads `/metrics/company_metrics.json` but nothing writes it. The evolution loop, board votes, and fitness function all read empty data on first run.

**Files:** `src/clawbot/scheduler.py`, `src/clawbot/metrics.py`

- [ ] **Step 1: After each executive cycle, write metrics**

In `_run_executive_cycle`, after publishing the directive, call:

```python
await self._write_metrics()

async def _write_metrics(self) -> None:
    from clawbot.gumroad import GumroadClient
    from clawbot.config import settings
    revenue = 0.0
    if settings.gumroad_api_key:
        try:
            client = GumroadClient(settings.gumroad_api_key)
            revenue = await client.sales_last_7_days_gbp()
        except Exception:
            pass  # don't crash the executive loop on a Gumroad API hiccup

    metrics = {
        "revenue_7d_gbp": revenue,
        "timestamp": datetime.now(UTC).isoformat(),
        "worker_count": await self._registry.worker_count() if self._registry else 0,
    }
    self._metrics_dir.mkdir(parents=True, exist_ok=True)
    path = self._metrics_dir / "company_metrics.json"
    path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
```

- [ ] **Step 2: Run tests, commit**

```bash
uv run python -m pytest tests/ -v
git commit -m "feat: scheduler writes company_metrics.json after each executive cycle"
```

---

### Task R4: Fix kill switch path mismatch

**Problem:** `monitor.py` hardcodes `KILL_FILE = Path("/tmp/clawbot.KILL")` but `docker-compose.yml` sets `KILL_FILE_PATH=/tmp/clawbot_kill/clawbot.KILL`. They don't match — the file-based kill switch would never fire in Docker.

**Files:** `src/clawbot/monitor.py`, `src/clawbot/config.py`

- [ ] **Step 1: Add to config**

```python
kill_file_path: str = "/tmp/clawbot.KILL"
```

- [ ] **Step 2: Update Monitor**

```python
# In Monitor.__init__, replace:
self._kill_file = kill_file
# with:
self._kill_file = Path(settings.kill_file_path) if kill_file is None else kill_file
```

- [ ] **Step 3: Update docker-compose.yml env**

```yaml
KILL_FILE_PATH: /tmp/clawbot_kill/clawbot.KILL
```

- [ ] **Step 4: Run tests, commit**

```bash
uv run python -m pytest tests/ -v
git commit -m "fix: kill switch path sourced from config — consistent between monitor and Docker"
```

---

### Task R5: Opportunity Scanner — Reddit interval fix

**Files:** `src/clawbot/opportunity_scanner.py`

- [ ] **Split to two loops: Reddit every 30 min, Companies House / FCA every 4 hours**

```python
REDDIT_INTERVAL_S = 1800
SLOW_INTERVAL_S = 14_400

async def run_forever(self) -> None:
    await asyncio.gather(self._reddit_loop(), self._slow_source_loop())

async def _reddit_loop(self) -> None:
    while True:
        await self._scan_reddit()
        await asyncio.sleep(REDDIT_INTERVAL_S)

async def _slow_source_loop(self) -> None:
    while True:
        await self._scan_slow_sources()
        await asyncio.sleep(SLOW_INTERVAL_S)
```

- [ ] **Commit:** `fix: opportunity scanner — Reddit 30min, slow sources 4h`

---

### Task R6: Revenue-first task queue

**Files:** `src/clawbot/scheduler.py`, `tests/test_scheduler.py`

- [ ] **Add TaskQueue with 80% hard cap on non-revenue tasks (see Task R2 in previous plan version for full code)**
- [ ] **Commit:** `feat: revenue-first task queue with 80/20 hard cap`

---

### Task R7: One-time human setup (do before `docker compose up`)

- [ ] Create LLM provider accounts: NIM, Groq, Google AI Studio, Cerebras (one each minimum)
- [ ] Create Gumroad account → get API key → set `GUMROAD_API_KEY`
- [ ] Register UK business entity (sole trader or Ltd) + notify HMRC of self-employment
- [ ] Open Monzo/Starling business account for GBP receipt
- [ ] Provision Hetzner CX32 and deploy:

```bash
ssh root@<VPS_IP>
apt update && apt install -y docker.io docker-compose-plugin git
git clone <your-repo> /opt/clawbot && cd /opt/clawbot
cp .env.example .env   # fill in all keys
docker compose up -d
docker compose logs -f clawbot
```

---

## Rate Budget (daily quotas respected)

| Agent tier | Cadence | Daily calls | Provider |
|---|---|---|---|
| Executives (5 agents) | 10 min | ~720 | Groq 70B (6K budget — 8× headroom) |
| Board votes + emergency | Daily + triggers | ~15 | NIM 70B |
| Lateral thinking | ~4 CEO decisions/day | ~28 | NIM 70B |
| Meta-evaluator | 1× daily | ~10 | NIM 70B |
| Dynamic workers (up to 20) | 10 min | ~2,880 | Groq 8B + Cerebras |
| Browser worker LLM calls | 20 RPM sustained | ~8,000 | Groq 8B (14.4K) + Cerebras (14.4K) |
| Opportunity scanner | 30 min Reddit, 4h slow | ~100 | Gemini Flash (1.5K budget) |
| **Total** | | **~11,750/day** | Within all provider daily budgets |

---

## Growth Model

| Phase | Revenue | Trigger | Action |
|---|---|---|---|
| Boot | £0 | Launch | CEO executes H1 (IR35 product on Gumroad) |
| First signal | £9-45 | First 1-5 sales | Evolution loop has gradient; CMO doubles down on what worked |
| Expansion | £90-450/month | 3+ products selling | CEO hires content-writer-001, researcher-001 workers |
| Scale | £500+/month | Stable revenue | Groq paid tier unlocked ($50/month = 4.7× more 70B calls) |
| Compounding | £2K+/month | Portfolio > 20 products | VPS upgrade CX52; 6 concurrent Chromium; worker cap raised to 40 |
