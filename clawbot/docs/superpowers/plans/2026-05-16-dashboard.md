# Clawbot Live Dashboard — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve a real-time mission-control dashboard from the VPS at port 8080 showing live executive status, a force-directed brain graph, activity feed, and kill clock.

**Architecture:** A FastAPI server starts in the same asyncio process as the scheduler (via `uvicorn.Server.serve()`), sharing the existing db/bus references. A `RedisReader` background coroutine subscribes to all bus streams and fans events into an `EventBroadcaster` that delivers SSE to connected browser clients. The frontend is a single `index.html` using D3.js for the brain graph and vanilla JS for everything else.

**Tech Stack:** FastAPI, uvicorn, D3.js (CDN), vanilla JS/CSS, asyncio, Redis XREAD, asyncpg (existing), numpy (existing)

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Modify | `pyproject.toml` | Add fastapi, uvicorn deps |
| Modify | `docker-compose.yml` | Expose port 8080 |
| Modify | `src/clawbot/scheduler.py` | Publish `{agent}.cycle_start` at cycle begin |
| Modify | `src/clawbot/main.py` | Subscribe cycle_start topics + start dashboard |
| Create | `src/clawbot/dashboard/__init__.py` | Empty package marker |
| Create | `src/clawbot/dashboard/server.py` | EventBroadcaster, BrainCache, RedisReader, FastAPI app, `start_dashboard()` |
| Create | `src/clawbot/dashboard/static/index.html` | Complete frontend: header, exec cards, D3 brain, feed, kill clock |
| Create | `tests/test_dashboard_server.py` | Unit tests for EventBroadcaster and compute_links |

---

## Task 1: Dependencies + Port

**Files:**
- Modify: `pyproject.toml`
- Modify: `docker-compose.yml`

- [ ] **Step 1: Add fastapi and uvicorn to pyproject.toml**

Open `pyproject.toml`. In `[project] dependencies`, add two entries:

```toml
[project]
dependencies = [
    "redis>=5.0",
    "httpx>=0.27",
    "pydantic-settings>=2.0",
    "python-dotenv>=1.0",
    "pgvector>=0.3",
    "asyncpg>=0.29",
    "browser-use>=0.1",
    "langchain-openai>=0.1",
    "tenacity>=8.0",
    "fastembed>=0.3",
    "numpy>=1.26",
    "fastapi>=0.111",
    "uvicorn[standard]>=0.29",
]
```

- [ ] **Step 2: Expose port 8080 in docker-compose.yml**

Add a `ports` block to the `clawbot` service (after `env_file: .env`):

```yaml
  clawbot:
    build: .
    restart: unless-stopped
    depends_on:
      redis:
        condition: service_healthy
      postgres:
        condition: service_healthy
    ports:
      - "8080:8080"
    env_file: .env
    volumes:
      ...
```

- [ ] **Step 3: Verify uv can resolve the new deps locally**

```bash
uv sync --no-dev
```

Expected: resolves without error (fastapi and uvicorn install). If uv.lock conflicts, run `uv lock --upgrade-package fastapi --upgrade-package uvicorn`.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml docker-compose.yml uv.lock
git commit -m "feat: add fastapi+uvicorn deps, expose port 8080"
```

---

## Task 2: Cycle-Start Events in Scheduler

**Files:**
- Modify: `src/clawbot/scheduler.py` (lines ~230–265 and ~360–395)

The dashboard needs to know when a cycle *begins* (so the card shows "thinking") not just when it completes (directive published). Add a `{agent}.cycle_start` publish at the top of each cycle function.

- [ ] **Step 1: Add publish to `_run_executive_cycle`**

In `src/clawbot/scheduler.py`, find `_run_executive_cycle`. Add the publish right after `soul_path, variant = self._pick_variant("ceo")`:

```python
    async def _run_executive_cycle(self) -> None:
        from clawbot.fitness_writer import append_observation

        self._executive_cycle_counter += 1
        soul_path, variant = self._pick_variant("ceo")
        if soul_path is None:
            return
        await self._bus.publish(
            "ceo.cycle_start",
            {"agent": "ceo", "ts": datetime.now(UTC).isoformat()},
        )
        soul = soul_path.read_text(encoding="utf-8")
        # ... rest of function unchanged
```

- [ ] **Step 2: Add publish to `_run_lieutenant_cycle`**

Find `_run_lieutenant_cycle`. Add publish after `if soul_path is None: return`:

```python
    async def _run_lieutenant_cycle(self, agent_id: str) -> None:
        from clawbot.fitness_writer import append_observation

        soul_path, variant = self._pick_variant(agent_id)
        if soul_path is None:
            return
        await self._bus.publish(
            f"{agent_id}.cycle_start",
            {"agent": agent_id, "ts": datetime.now(UTC).isoformat()},
        )
        soul = soul_path.read_text(encoding="utf-8")
        # ... rest of function unchanged
```

- [ ] **Step 3: Run existing tests to confirm nothing broke**

```bash
uv run pytest tests/test_scheduler.py -x -q
```

Expected: all 12 tests pass.

- [ ] **Step 4: Commit**

```bash
git add src/clawbot/scheduler.py
git commit -m "feat: publish cycle_start events to bus for dashboard telemetry"
```

---

## Task 3: EventBroadcaster and compute_links — Tests First

**Files:**
- Create: `tests/test_dashboard_server.py`
- Create: `src/clawbot/dashboard/__init__.py`
- Create: `src/clawbot/dashboard/server.py` (EventBroadcaster + compute_links only)

- [ ] **Step 1: Create empty package marker**

Create `src/clawbot/dashboard/__init__.py` with empty content.

- [ ] **Step 2: Write failing tests**

Create `tests/test_dashboard_server.py`:

```python
"""Tests for EventBroadcaster and compute_links in dashboard.server."""
import asyncio
import pytest
from clawbot.dashboard.server import EventBroadcaster, compute_links


class TestEventBroadcaster:
    @pytest.mark.asyncio
    async def test_subscribe_returns_queue(self):
        bc = EventBroadcaster()
        q = bc.subscribe()
        assert q is not None

    @pytest.mark.asyncio
    async def test_broadcast_delivers_to_subscriber(self):
        bc = EventBroadcaster()
        q = bc.subscribe()
        await bc.broadcast({"type": "test", "value": 42})
        msg = q.get_nowait()
        assert '"type": "test"' in msg
        assert '"value": 42' in msg

    @pytest.mark.asyncio
    async def test_broadcast_to_multiple_subscribers(self):
        bc = EventBroadcaster()
        q1 = bc.subscribe()
        q2 = bc.subscribe()
        await bc.broadcast({"x": 1})
        assert not q1.empty()
        assert not q2.empty()

    @pytest.mark.asyncio
    async def test_unsubscribe_removes_queue(self):
        bc = EventBroadcaster()
        q = bc.subscribe()
        bc.unsubscribe(q)
        await bc.broadcast({"x": 1})
        assert q.empty()

    @pytest.mark.asyncio
    async def test_full_queue_drops_message_without_raising(self):
        bc = EventBroadcaster()
        q = bc.subscribe()
        for _ in range(q.maxsize):
            await bc.broadcast({"x": 1})
        # This should not raise even though the queue is full
        await bc.broadcast({"x": 2})


class TestComputeLinks:
    def test_empty_returns_no_links(self):
        assert compute_links([]) == []

    def test_single_node_returns_no_links(self):
        node = {"id": 1, "embedding": [1.0, 0.0]}
        assert compute_links([node]) == []

    def test_identical_embeddings_are_linked(self):
        nodes = [
            {"id": 1, "embedding": [1.0, 0.0, 0.0]},
            {"id": 2, "embedding": [1.0, 0.0, 0.0]},
        ]
        links = compute_links(nodes)
        assert len(links) == 1
        assert links[0]["source"] == 1
        assert links[0]["target"] == 2
        assert abs(links[0]["strength"] - 1.0) < 1e-4

    def test_orthogonal_embeddings_not_linked(self):
        nodes = [
            {"id": 1, "embedding": [1.0, 0.0, 0.0]},
            {"id": 2, "embedding": [0.0, 1.0, 0.0]},
        ]
        links = compute_links(nodes, threshold=0.7)
        assert links == []

    def test_threshold_filters_weak_links(self):
        # cos([1,1,0], [1,0,0]) = 1/sqrt(2) ≈ 0.707
        nodes = [
            {"id": 1, "embedding": [1.0, 1.0, 0.0]},
            {"id": 2, "embedding": [1.0, 0.0, 0.0]},
        ]
        assert len(compute_links(nodes, threshold=0.71)) == 0
        assert len(compute_links(nodes, threshold=0.70)) == 1
```

- [ ] **Step 3: Run tests to confirm they fail**

```bash
uv run pytest tests/test_dashboard_server.py -x -q
```

Expected: `ModuleNotFoundError: No module named 'clawbot.dashboard.server'`

- [ ] **Step 4: Implement EventBroadcaster and compute_links**

Create `src/clawbot/dashboard/server.py` with just these two components for now:

```python
"""FastAPI dashboard server — EventBroadcaster, brain helpers, SSE endpoint."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


class EventBroadcaster:
    """Fan-out: one writer, N SSE clients each get their own queue."""

    def __init__(self) -> None:
        self._queues: list[asyncio.Queue[str]] = []

    def subscribe(self) -> asyncio.Queue[str]:
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=200)
        self._queues.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[str]) -> None:
        try:
            self._queues.remove(q)
        except ValueError:
            pass

    async def broadcast(self, event: dict[str, Any]) -> None:
        data = json.dumps(event)
        for q in list(self._queues):
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                pass  # slow client — drop rather than block


def compute_links(
    nodes: list[dict[str, Any]], threshold: float = 0.72
) -> list[dict[str, Any]]:
    """Return pairs of node IDs whose embedding cosine similarity >= threshold."""
    if len(nodes) < 2:
        return []
    embeddings = np.array([n["embedding"] for n in nodes], dtype=np.float32)
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    normalized = embeddings / (norms + 1e-8)
    sim: np.ndarray = normalized @ normalized.T
    links = []
    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            s = float(sim[i, j])
            if s >= threshold:
                links.append({"source": nodes[i]["id"], "target": nodes[j]["id"], "strength": round(s, 3)})
    return links
```

- [ ] **Step 5: Run tests to confirm they pass**

```bash
uv run pytest tests/test_dashboard_server.py -x -q
```

Expected: all 9 tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/clawbot/dashboard/__init__.py src/clawbot/dashboard/server.py tests/test_dashboard_server.py
git commit -m "feat: EventBroadcaster + compute_links with tests"
```

---

## Task 4: Complete server.py — BrainCache, RedisReader, FastAPI routes

**Files:**
- Modify: `src/clawbot/dashboard/server.py` (add BrainCache, RedisReader, FastAPI app, start_dashboard)

This task has no new tests — the components are integration-level (postgres + Redis). The existing tests for EventBroadcaster and compute_links remain green throughout.

- [ ] **Step 1: Add BrainCache to server.py**

Append to `src/clawbot/dashboard/server.py` after `compute_links`:

```python
import time
from datetime import datetime, UTC


class BrainCache:
    """Queries postgres for knowledge nodes + computes similarity links. Cached 30s."""

    _TTL = 30.0

    def __init__(self, db_pool: Any) -> None:
        self._pool = db_pool
        self._cached_at: float = 0.0
        self._data: dict[str, Any] = {"nodes": [], "links": []}

    async def get(self) -> dict[str, Any]:
        if time.monotonic() - self._cached_at < self._TTL:
            return self._data
        rows = await self._pool.fetch(
            "SELECT id, content, category, embedding, created_at FROM knowledge ORDER BY id"
        )
        now = datetime.now(UTC)
        nodes = []
        for row in rows:
            emb = list(row["embedding"]) if row["embedding"] is not None else []
            age_days = (now - row["created_at"].replace(tzinfo=UTC)).total_seconds() / 86400
            nodes.append({
                "id": row["id"],
                "content_preview": row["content"][:120],
                "category": row["category"] or "general",
                "embedding": emb,
                "age_days": round(age_days, 2),
            })
        links = compute_links(nodes) if nodes else []
        # Strip embeddings before serving — frontend doesn't need them
        for n in nodes:
            del n["embedding"]
        self._data = {"nodes": nodes, "links": links}
        self._cached_at = time.monotonic()
        return self._data
```

- [ ] **Step 2: Add RedisReader to server.py**

Append to `src/clawbot/dashboard/server.py`:

```python
WATCHED_STREAMS = [
    "ceo.cycle_start", "cfo.cycle_start", "cmo.cycle_start", "coo.cycle_start", "cto.cycle_start",
    "ceo.directive",   "cfo.directive",   "cmo.directive",   "coo.directive",   "cto.directive",
    "operator.escalation",
]
STREAM_PREFIX = "clawbot:bus"


class RedisReader:
    """Tails watched Redis streams and fans events into the broadcaster."""

    def __init__(self, redis_url: str, broadcaster: EventBroadcaster) -> None:
        self._url = redis_url
        self._bc = broadcaster
        self._last_ids: dict[str, str] = {}

    async def run_forever(self) -> None:
        import redis.asyncio as aioredis
        r = await aioredis.from_url(self._url, decode_responses=True)
        stream_keys = {f"{STREAM_PREFIX}:{t}": t for t in WATCHED_STREAMS}
        # Start reading from now ($ = only new messages)
        self._last_ids = {k: "$" for k in stream_keys}
        while True:
            try:
                results = await r.xread(self._last_ids, count=20, block=1000)
                for stream_key, messages in (results or []):
                    topic = stream_keys.get(stream_key, stream_key)
                    for msg_id, fields in messages:
                        self._last_ids[stream_key] = msg_id
                        await self._handle(topic, fields)
            except Exception as exc:
                logger.warning("RedisReader error: %s", exc)
                await asyncio.sleep(2)

    async def _handle(self, topic: str, fields: dict[str, str]) -> None:
        try:
            payload = json.loads(fields.get("payload", "{}"))
        except json.JSONDecodeError:
            return

        if topic.endswith(".cycle_start"):
            agent = payload.get("agent", topic.split(".")[0])
            await self._bc.broadcast({"type": "cycle_start", "agent": agent, "ts": payload.get("ts", "")})

        elif topic.endswith(".directive"):
            agent = topic.split(".")[0]
            response_raw = payload.get("response", "")
            action = _extract_action(response_raw)
            await self._bc.broadcast({
                "type": "cycle_complete",
                "agent": agent,
                "success": True,
                "action": action,
                "ts": payload.get("ts", ""),
            })

        elif topic == "operator.escalation":
            await self._bc.broadcast({
                "type": "escalation",
                "from_agent": payload.get("from_agent", ""),
                "severity": payload.get("severity", "info"),
                "summary": payload.get("summary", ""),
                "ts": payload.get("ts", ""),
            })


def _extract_action(response_raw: str) -> str:
    """Pull action/directive text from LLM JSON response, falling back to raw text."""
    try:
        import re
        match = re.search(r"```(?:json)?\s*([\s\S]+?)```", response_raw)
        blob = match.group(1) if match else response_raw
        start, end = blob.find("{"), blob.rfind("}")
        if start != -1 and end != -1:
            data = json.loads(blob[start: end + 1])
            return str(data.get("action") or data.get("directive") or "")[:200]
    except Exception:
        pass
    return response_raw[:200]
```

- [ ] **Step 3: Add FastAPI app and start_dashboard to server.py**

Append to `src/clawbot/dashboard/server.py`:

```python
import json as _json
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles


METRICS_DIR = Path("/metrics")
FOUNDED = "2026-05-16"
EXECUTIVES = ["ceo", "cfo", "cmo", "coo", "cto"]

_broadcaster: EventBroadcaster | None = None
_brain_cache: BrainCache | None = None


def create_app(db_pool: Any, redis_url: str) -> FastAPI:
    global _broadcaster, _brain_cache
    _broadcaster = EventBroadcaster()
    _brain_cache = BrainCache(db_pool)

    app = FastAPI(docs_url=None, redoc_url=None)

    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return (static_dir / "index.html").read_text(encoding="utf-8")

    @app.get("/api/brain")
    async def brain():
        assert _brain_cache is not None
        data = await _brain_cache.get()
        return JSONResponse(data)

    @app.get("/api/state")
    async def state():
        return JSONResponse(_build_state_snapshot())

    @app.get("/api/events")
    async def events(request: Request):
        assert _broadcaster is not None

        async def generate():
            q = _broadcaster.subscribe()
            try:
                # Send initial heartbeat so browser knows connection is live
                yield "data: {\"type\": \"heartbeat\"}\n\n"
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        data = await asyncio.wait_for(q.get(), timeout=15.0)
                        yield f"data: {data}\n\n"
                    except asyncio.TimeoutError:
                        yield "data: {\"type\": \"heartbeat\"}\n\n"
            finally:
                _broadcaster.unsubscribe(q)

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app


def _build_state_snapshot() -> dict[str, Any]:
    """Read metrics files for initial page load state."""
    agents: dict[str, Any] = {}
    for agent_id in EXECUTIVES:
        obs_path = METRICS_DIR / agent_id / "observations.jsonl"
        cycles: list[bool] = []
        last_action = ""
        if obs_path.exists():
            lines = obs_path.read_text(encoding="utf-8").splitlines()
            for line in lines[-20:]:
                try:
                    entry = json.loads(line)
                    cycles.append(bool(entry.get("success", False)))
                    if entry.get("success") and entry.get("kind", "").endswith("_cycle"):
                        last_action = entry.get("summary", "")
                except Exception:
                    pass
        agents[agent_id] = {"status": "idle", "cycles": cycles[-10:], "last_action": last_action}

    revenue = 0.0
    metrics_path = METRICS_DIR / "company_metrics.json"
    if metrics_path.exists():
        try:
            revenue = json.loads(metrics_path.read_text())["revenue_7d_gbp"]
        except Exception:
            pass

    escalations: list[dict] = []
    esc_path = METRICS_DIR / "escalations.jsonl"
    if esc_path.exists():
        for line in esc_path.read_text(encoding="utf-8").splitlines()[-20:]:
            try:
                escalations.append(json.loads(line))
            except Exception:
                pass

    from datetime import date
    day = (date.today() - date.fromisoformat(FOUNDED)).days + 1

    return {
        "agents": agents,
        "metrics": {"revenue_7d_gbp": revenue},
        "kill_clock": {"day": day, "founded": FOUNDED, "max_days": 60},
        "recent_escalations": escalations[-15:],
    }


async def start_dashboard(db_pool: Any, redis_url: str) -> None:
    """Launch FastAPI + background Redis reader. Designed to run as an asyncio task."""
    import uvicorn

    app = create_app(db_pool=db_pool, redis_url=redis_url)

    assert _broadcaster is not None
    reader = RedisReader(redis_url=redis_url, broadcaster=_broadcaster)

    config = uvicorn.Config(app, host="0.0.0.0", port=8080, log_level="warning", access_log=False)
    server = uvicorn.Server(config)

    await asyncio.gather(
        server.serve(),
        reader.run_forever(),
    )
```

- [ ] **Step 4: Run tests to confirm nothing broke**

```bash
uv run pytest tests/test_dashboard_server.py -x -q
```

Expected: all 9 tests still pass.

- [ ] **Step 5: Commit**

```bash
git add src/clawbot/dashboard/server.py
git commit -m "feat: BrainCache, RedisReader, FastAPI routes for dashboard"
```

---

## Task 5: Wire dashboard into main.py

**Files:**
- Modify: `src/clawbot/main.py`

- [ ] **Step 1: Subscribe to cycle_start topics and start dashboard**

In `main.py`, add the five `cycle_start` topics to the `topics` list and add `start_dashboard` to the `asyncio.gather` call:

```python
# At the top of main.py, add import:
from clawbot.dashboard.server import start_dashboard

# In async def main(), update topics list:
    topics = [
        "ceo.directive", "board.resolution", "coo.task", "cmo.campaign",
        "code.change_request", "operator.escalation", "operator.reply",
        "operator.message",
        "ceo.cycle_start", "cfo.cycle_start", "cmo.cycle_start",
        "coo.cycle_start", "cto.cycle_start",
    ]

# Replace:
    try:
        await scheduler.run_forever()

# With:
    try:
        await asyncio.gather(
            scheduler.run_forever(),
            start_dashboard(db_pool=db.pool, redis_url=settings.redis_url),
        )
```

- [ ] **Step 2: Run all tests**

```bash
uv run pytest -x -q
```

Expected: all tests pass (255+9 = 264 or current count + 9).

- [ ] **Step 3: Commit**

```bash
git add src/clawbot/main.py
git commit -m "feat: start dashboard server alongside scheduler in main"
```

---

## Task 6: Frontend — index.html

**Files:**
- Create: `src/clawbot/dashboard/static/index.html`

This is the entire frontend. One file, no build step, no framework. D3.js loaded from CDN.

- [ ] **Step 1: Create index.html**

Create `src/clawbot/dashboard/static/index.html` with the full content below.

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Clawbot HQ</title>
<script src="https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js"></script>
<style>
:root {
  --bg: #080c17;
  --surface: rgba(255,255,255,0.035);
  --surface-hover: rgba(255,255,255,0.06);
  --border: rgba(255,255,255,0.07);
  --cyan: #00d4ff;
  --cyan-dim: rgba(0,212,255,0.15);
  --green: #10b981;
  --red: #ef4444;
  --amber: #f59e0b;
  --purple: #818cf8;
  --blue: #60a5fa;
  --orange: #fb923c;
  --text: #e2e8f0;
  --muted: #64748b;
  --muted2: #334155;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:'Inter',system-ui,sans-serif;height:100vh;overflow:hidden;display:flex;flex-direction:column;font-size:13px}

/* ── HEADER ─────────────────────────────────────────────────────────── */
header{
  display:flex;align-items:center;gap:16px;
  padding:10px 20px;
  border-bottom:1px solid var(--border);
  flex-shrink:0;
  background:rgba(8,12,23,0.9);
  backdrop-filter:blur(12px);
}
.logo{font-size:15px;font-weight:700;letter-spacing:.08em;color:var(--text)}
.logo span{color:var(--cyan)}
.status-dot{width:7px;height:7px;border-radius:50%;background:var(--green);box-shadow:0 0 6px var(--green);animation:pulse-green 2s infinite}
@keyframes pulse-green{0%,100%{opacity:1}50%{opacity:.5}}
.header-spacer{flex:1}
#revenue-display{
  font-size:20px;font-weight:700;color:var(--green);
  font-variant-numeric:tabular-nums;
  text-shadow:0 0 20px rgba(16,185,129,.4);
}
.kill-clock{
  display:flex;flex-direction:column;align-items:flex-end;gap:2px;
}
.kill-day{font-size:11px;color:var(--muted);font-weight:500}
.kill-bar-wrap{width:120px;height:4px;background:var(--muted2);border-radius:2px;overflow:hidden}
.kill-bar{height:100%;border-radius:2px;background:var(--green);transition:width .5s,background .5s}

/* ── MAIN GRID ───────────────────────────────────────────────────────── */
main{
  flex:1;overflow:hidden;
  display:grid;
  grid-template-rows:140px 1fr;
  grid-template-columns:1fr 360px;
  gap:1px;
  background:var(--border);
}

/* ── EXECUTIVE STRIP ─────────────────────────────────────────────────── */
.exec-strip{
  grid-column:1/-1;
  display:flex;gap:1px;
  background:var(--border);
  overflow:hidden;
}
.exec-card{
  flex:1;padding:14px 16px;
  background:var(--bg);
  display:flex;flex-direction:column;gap:6px;
  cursor:default;
  transition:background .2s;
  position:relative;overflow:hidden;
}
.exec-card::before{
  content:'';position:absolute;inset:0;
  background:linear-gradient(135deg,transparent 60%,var(--cyan-dim));
  opacity:0;transition:opacity .4s;
}
.exec-card.thinking::before{opacity:1}
.exec-card.thinking{background:rgba(0,212,255,.04)}
.exec-card.error{background:rgba(239,68,68,.04)}
.exec-card-header{display:flex;align-items:center;gap:8px}
.exec-id{font-size:11px;font-weight:700;letter-spacing:.12em;color:var(--muted);text-transform:uppercase}
.exec-status-dot{width:6px;height:6px;border-radius:50%;background:var(--muted2);flex-shrink:0;transition:background .3s,box-shadow .3s}
.exec-card.thinking .exec-status-dot{background:var(--cyan);box-shadow:0 0 8px var(--cyan);animation:pulse-cyan 1s infinite}
.exec-card.success .exec-status-dot{background:var(--green)}
.exec-card.error .exec-status-dot{background:var(--red);box-shadow:0 0 6px var(--red)}
@keyframes pulse-cyan{0%,100%{opacity:1}50%{opacity:.4}}
.exec-status-label{font-size:10px;color:var(--muted);font-weight:500;margin-left:auto}
.exec-action{
  font-size:11px;color:var(--text);line-height:1.5;
  display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;
  min-height:48px;
  opacity:.75;
}
.exec-cycles{display:flex;gap:3px;align-items:center;margin-top:auto}
.cycle-dot{width:5px;height:5px;border-radius:50%;flex-shrink:0}
.cycle-dot.ok{background:var(--green);opacity:.7}
.cycle-dot.fail{background:var(--red);opacity:.8}
.cycle-dot.unknown{background:var(--muted2)}

/* ── BRAIN GRAPH ─────────────────────────────────────────────────────── */
#brain-container{
  background:var(--bg);
  position:relative;overflow:hidden;
}
#brain-container h2{
  position:absolute;top:14px;left:16px;
  font-size:10px;font-weight:700;letter-spacing:.12em;
  color:var(--muted);text-transform:uppercase;z-index:2;
}
#brain-svg{width:100%;height:100%}
.brain-node{cursor:pointer;transition:opacity .2s}
.brain-link{stroke:rgba(255,255,255,.06);fill:none}

/* ── TOOLTIP ─────────────────────────────────────────────────────────── */
#tooltip{
  position:fixed;z-index:100;
  background:rgba(15,20,35,.95);
  border:1px solid var(--border);
  border-radius:8px;padding:10px 13px;
  font-size:11px;line-height:1.6;max-width:260px;
  pointer-events:none;display:none;
  backdrop-filter:blur(12px);
}
#tooltip .tt-cat{font-size:9px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;margin-bottom:4px}

/* ── ACTIVITY FEED ───────────────────────────────────────────────────── */
#feed-container{
  background:var(--bg);
  display:flex;flex-direction:column;
  overflow:hidden;
}
#feed-container h2{
  font-size:10px;font-weight:700;letter-spacing:.12em;
  color:var(--muted);text-transform:uppercase;
  padding:14px 16px 10px;flex-shrink:0;
  border-bottom:1px solid var(--border);
}
#feed{
  flex:1;overflow-y:auto;padding:8px 0;
  scrollbar-width:thin;scrollbar-color:var(--muted2) transparent;
}
.feed-item{
  padding:8px 16px;
  border-left:2px solid transparent;
  margin-bottom:1px;
  cursor:default;
}
.feed-item:hover{background:var(--surface)}
.feed-item.type-escalation.sev-info{border-color:var(--blue)}
.feed-item.type-escalation.sev-request{border-color:var(--amber)}
.feed-item.type-escalation.sev-warning{border-color:var(--orange)}
.feed-item.type-escalation.sev-urgent{border-color:var(--red)}
.feed-item.type-directive{border-color:var(--cyan)}
.feed-item.type-error{border-color:var(--red)}
.feed-item.type-brain{border-color:var(--purple)}
.feed-meta{display:flex;gap:6px;align-items:baseline;margin-bottom:2px}
.feed-time{font-size:10px;color:var(--muted);font-variant-numeric:tabular-nums}
.feed-agent{font-size:10px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
.feed-badge{font-size:9px;padding:1px 5px;border-radius:3px;font-weight:700;letter-spacing:.06em}
.badge-request{background:rgba(245,158,11,.15);color:var(--amber)}
.badge-warning{background:rgba(251,146,60,.15);color:var(--orange)}
.badge-urgent{background:rgba(239,68,68,.2);color:var(--red)}
.badge-info{background:rgba(96,165,250,.1);color:var(--blue)}
.badge-directive{background:rgba(0,212,255,.1);color:var(--cyan)}
.badge-error{background:rgba(239,68,68,.1);color:var(--red)}
.feed-text{font-size:11px;color:var(--text);line-height:1.5;opacity:.8}

/* ── BRAIN LEGEND ────────────────────────────────────────────────────── */
#legend{
  position:absolute;bottom:14px;left:16px;
  display:flex;gap:12px;align-items:center;z-index:2;
}
.legend-item{display:flex;gap:5px;align-items:center;font-size:10px;color:var(--muted)}
.legend-dot{width:7px;height:7px;border-radius:50%}
</style>
</head>
<body>

<header>
  <div class="logo">CLAWBOT <span>LTD</span></div>
  <div class="status-dot"></div>
  <div class="header-spacer"></div>
  <div id="revenue-display">£0.00</div>
  <div class="kill-clock">
    <div class="kill-day" id="kill-day-text">Day 1 of 60</div>
    <div class="kill-bar-wrap"><div class="kill-bar" id="kill-bar" style="width:1%"></div></div>
  </div>
</header>

<main>
  <div class="exec-strip" id="exec-strip"></div>

  <div id="brain-container">
    <h2>Company Brain</h2>
    <svg id="brain-svg"></svg>
    <div id="legend"></div>
  </div>

  <div id="feed-container">
    <h2>Live Activity</h2>
    <div id="feed"></div>
  </div>
</main>

<div id="tooltip"></div>

<script>
// ── Constants ────────────────────────────────────────────────────────────
const AGENTS = ['ceo','cfo','cmo','coo','cto'];
const AGENT_ROLES = {ceo:'Chief Executive',cfo:'Chief Financial',cmo:'Chief Marketing',coo:'Chief Operating',cto:'Chief Technology'};
const CAT_COLORS = {strategy:'#818cf8',opportunity:'#10b981',decision:'#fb923c',metric:'#60a5fa',general:'#64748b'};
const SEV_COLORS = {info:'#60a5fa',request:'#f59e0b',warning:'#fb923c',urgent:'#ef4444'};
const FOUNDED = new Date('2026-05-16');

// ── State ────────────────────────────────────────────────────────────────
const agentState = {};
AGENTS.forEach(id => {
  agentState[id] = {status:'idle', cycles:[], lastAction:'Awaiting first cycle…', cycleStart:null};
});

// ── Kill clock ────────────────────────────────────────────────────────────
function updateKillClock(revenue) {
  const day = Math.max(1, Math.floor((Date.now() - FOUNDED.getTime()) / 86400000) + 1);
  const pct = Math.min(100, (day / 60) * 100);
  document.getElementById('kill-day-text').textContent = `Day ${day} of 60`;
  const bar = document.getElementById('kill-bar');
  bar.style.width = pct + '%';
  bar.style.background = pct < 50 ? '#10b981' : pct < 83 ? '#f59e0b' : '#ef4444';
}
updateKillClock(0);

// ── Revenue display ──────────────────────────────────────────────────────
function setRevenue(gbp) {
  document.getElementById('revenue-display').textContent = '£' + parseFloat(gbp).toFixed(2);
}

// ── Executive cards ───────────────────────────────────────────────────────
function renderExecStrip() {
  const strip = document.getElementById('exec-strip');
  strip.innerHTML = '';
  AGENTS.forEach(id => {
    const s = agentState[id];
    const card = document.createElement('div');
    card.className = 'exec-card ' + s.status;
    card.id = 'card-' + id;
    card.innerHTML = `
      <div class="exec-card-header">
        <span class="exec-id">${id.toUpperCase()}</span>
        <span class="exec-status-dot"></span>
        <span class="exec-status-label">${statusLabel(s)}</span>
      </div>
      <div class="exec-action">${escHtml(s.lastAction)}</div>
      <div class="exec-cycles">${renderCycleDots(s.cycles)}</div>
    `;
    strip.appendChild(card);
  });
}

function statusLabel(s) {
  if (s.status === 'thinking' && s.cycleStart) {
    const secs = Math.round((Date.now() - s.cycleStart) / 1000);
    return `thinking ${secs}s`;
  }
  return s.status;
}

function renderCycleDots(cycles) {
  return cycles.map(ok => `<div class="cycle-dot ${ok===true?'ok':ok===false?'fail':'unknown'}"></div>`).join('');
}

function updateCard(id) {
  const card = document.getElementById('card-' + id);
  if (!card) return;
  const s = agentState[id];
  card.className = 'exec-card ' + s.status;
  card.querySelector('.exec-status-label').textContent = statusLabel(s);
  card.querySelector('.exec-action').innerHTML = escHtml(s.lastAction);
  card.querySelector('.exec-cycles').innerHTML = renderCycleDots(s.cycles);
}

// Update status labels every second for "thinking Xs" counter
setInterval(() => {
  AGENTS.forEach(id => { if (agentState[id].status === 'thinking') updateCard(id); });
}, 1000);

// ── Brain graph (D3 force) ────────────────────────────────────────────────
const svg = d3.select('#brain-svg');
const container = document.getElementById('brain-container');
let W = container.clientWidth, H = container.clientHeight;

const g = svg.append('g').attr('transform', `translate(0,30)`);
const linkGroup = g.append('g').attr('class', 'links');
const nodeGroup = g.append('g').attr('class', 'nodes');

const sim = d3.forceSimulation()
  .force('link', d3.forceLink().id(d => d.id).distance(55).strength(d => d.strength * 0.5))
  .force('charge', d3.forceManyBody().strength(-90))
  .force('center', d3.forceCenter(W / 2, (H - 30) / 2))
  .force('collision', d3.forceCollide(12));

let brainNodes = [], brainLinks = [];
let linkSel = linkGroup.selectAll('line');
let nodeSel = nodeGroup.selectAll('circle');

function updateBrain(data) {
  brainNodes = data.nodes;
  brainLinks = data.links;

  linkSel = linkGroup.selectAll('line')
    .data(brainLinks, d => `${d.source}-${d.target}`)
    .join(
      enter => enter.append('line').attr('class','brain-link').attr('stroke-width', d => d.strength),
      update => update,
      exit => exit.remove()
    );

  nodeSel = nodeGroup.selectAll('circle')
    .data(brainNodes, d => d.id)
    .join(
      enter => enter.append('circle')
        .attr('class', 'brain-node')
        .attr('r', 0)
        .attr('fill', d => CAT_COLORS[d.category] || CAT_COLORS.general)
        .attr('opacity', d => Math.max(0.3, 1 - d.age_days / 30))
        .on('mouseover', showTooltip)
        .on('mousemove', moveTooltip)
        .on('mouseout', hideTooltip)
        .call(enter => enter.transition().duration(600).attr('r', d => Math.max(4, 7 - d.age_days * 0.5))),
      update => update.attr('fill', d => CAT_COLORS[d.category] || CAT_COLORS.general),
      exit => exit.transition().duration(300).attr('r', 0).remove()
    );

  sim.nodes(brainNodes);
  sim.force('link').links(brainLinks);
  sim.alpha(0.4).restart();
}

sim.on('tick', () => {
  linkSel
    .attr('x1', d => d.source.x).attr('y1', d => d.source.y)
    .attr('x2', d => d.target.x).attr('y2', d => d.target.y);
  nodeSel
    .attr('cx', d => Math.max(10, Math.min(W - 10, d.x)))
    .attr('cy', d => Math.max(10, Math.min(H - 40, d.y)));
});

// Brain legend
function renderLegend() {
  const legend = document.getElementById('legend');
  legend.innerHTML = Object.entries(CAT_COLORS).map(([cat, color]) =>
    `<div class="legend-item"><div class="legend-dot" style="background:${color}"></div>${cat}</div>`
  ).join('');
}
renderLegend();

// Tooltip
const tooltip = document.getElementById('tooltip');
function showTooltip(event, d) {
  tooltip.style.display = 'block';
  tooltip.innerHTML = `<div class="tt-cat" style="color:${CAT_COLORS[d.category]||CAT_COLORS.general}">${d.category}</div>${escHtml(d.content_preview)}`;
}
function moveTooltip(event) {
  tooltip.style.left = (event.clientX + 12) + 'px';
  tooltip.style.top = (event.clientY - 8) + 'px';
}
function hideTooltip() { tooltip.style.display = 'none'; }

// ── Activity feed ─────────────────────────────────────────────────────────
const feed = document.getElementById('feed');
const MAX_FEED = 80;

function addFeedItem(item) {
  const div = document.createElement('div');
  const typeClass = `type-${item.type}`;
  const sevClass = item.severity ? `sev-${item.severity}` : '';
  div.className = `feed-item ${typeClass} ${sevClass}`;

  let badge = '', text = '';
  const time = formatTime(item.ts);

  if (item.type === 'escalation') {
    badge = `<span class="feed-badge badge-${item.severity}">${item.severity.toUpperCase()}</span>`;
    text = item.summary || '';
  } else if (item.type === 'cycle_complete') {
    badge = `<span class="feed-badge badge-directive">DIRECTIVE</span>`;
    text = item.action || 'cycle complete';
  } else if (item.type === 'cycle_start') {
    return; // Don't add feed item for starts — just update card
  } else {
    text = item.summary || item.action || JSON.stringify(item);
  }

  div.innerHTML = `
    <div class="feed-meta">
      <span class="feed-time">${time}</span>
      <span class="feed-agent">${item.from_agent || item.agent || ''}</span>
      ${badge}
    </div>
    <div class="feed-text">${escHtml(text)}</div>
  `;

  feed.insertBefore(div, feed.firstChild);
  while (feed.children.length > MAX_FEED) feed.removeChild(feed.lastChild);
}

// Load recent escalations from initial state
function loadInitialFeed(escalations) {
  [...escalations].reverse().forEach(esc => {
    addFeedItem({type:'escalation', from_agent:esc.from_agent, severity:esc.severity, summary:esc.summary, ts:esc.ts});
  });
}

// ── SSE event handling ────────────────────────────────────────────────────
function handleEvent(event) {
  if (event.type === 'heartbeat') return;

  if (event.type === 'cycle_start') {
    const s = agentState[event.agent];
    if (s) { s.status = 'thinking'; s.cycleStart = Date.now(); updateCard(event.agent); }
  }

  if (event.type === 'cycle_complete') {
    const s = agentState[event.agent];
    if (s) {
      s.status = event.success ? 'success' : 'error';
      s.cycleStart = null;
      if (event.action) s.lastAction = event.action;
      s.cycles = [...s.cycles.slice(-9), event.success];
      updateCard(event.agent);
      addFeedItem(event);
      // Reset to idle after 3s
      setTimeout(() => { if (agentState[event.agent]) { agentState[event.agent].status = 'idle'; updateCard(event.agent); } }, 3000);
    }
  }

  if (event.type === 'escalation') {
    addFeedItem(event);
  }

  if (event.type === 'metrics') {
    setRevenue(event.revenue_7d_gbp || 0);
  }
}

// ── Boot sequence ─────────────────────────────────────────────────────────
renderExecStrip();

// 1. Load initial state snapshot
fetch('/api/state').then(r => r.json()).then(state => {
  // Populate agent cards from observations
  Object.entries(state.agents || {}).forEach(([id, data]) => {
    if (agentState[id]) {
      agentState[id].cycles = data.cycles || [];
      if (data.last_action) agentState[id].lastAction = data.last_action;
    }
  });
  renderExecStrip();

  // Revenue + kill clock
  setRevenue((state.metrics || {}).revenue_7d_gbp || 0);
  updateKillClock();

  // Feed
  loadInitialFeed(state.recent_escalations || []);
});

// 2. Load brain
function refreshBrain() {
  fetch('/api/brain').then(r => r.json()).then(data => updateBrain(data)).catch(() => {});
}
refreshBrain();
setInterval(refreshBrain, 30000);

// 3. SSE connection
function connectSSE() {
  const es = new EventSource('/api/events');
  es.onmessage = e => { try { handleEvent(JSON.parse(e.data)); } catch {} };
  es.onerror = () => { es.close(); setTimeout(connectSSE, 3000); };
}
connectSSE();

// ── Utilities ─────────────────────────────────────────────────────────────
function escHtml(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function formatTime(ts) {
  if (!ts) return '';
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit',second:'2-digit'});
  } catch { return ts.slice(11,19) || ''; }
}

// Handle resize
window.addEventListener('resize', () => {
  W = container.clientWidth; H = container.clientHeight;
  sim.force('center', d3.forceCenter(W / 2, (H - 30) / 2)).alpha(0.1).restart();
});
</script>
</body>
</html>
```

- [ ] **Step 2: Verify file exists and is non-empty**

```bash
wc -c src/clawbot/dashboard/static/index.html
```

Expected: at least 8000 bytes.

- [ ] **Step 3: Commit**

```bash
git add src/clawbot/dashboard/static/index.html
git commit -m "feat: dashboard frontend — exec cards, D3 brain graph, live feed, kill clock"
```

---

## Task 7: Deploy and Smoke Test

**Files:** None new — full redeploy needed (new deps, new port)

- [ ] **Step 1: Full redeploy from local machine**

```bash
cd /c/Users/Winte && \
tar --exclude='clawbot/.venv' --exclude='clawbot/__pycache__' \
    --exclude='clawbot/.pytest_cache' --exclude='clawbot/.ruff_cache' \
    --exclude='clawbot/kill' \
    -czf /tmp/clawbot-deploy.tar.gz clawbot && \
scp /tmp/clawbot-deploy.tar.gz clawbot:/tmp/clawbot-deploy.tar.gz && \
ssh clawbot 'tar -xzf /tmp/clawbot-deploy.tar.gz -C /opt --overwrite && mkdir -p /opt/clawbot/kill'
```

```bash
ssh clawbot 'cd /opt/clawbot && docker compose down && docker compose up -d --build'
```

Expected: build completes, all three containers start.

- [ ] **Step 2: Confirm port 8080 is reachable**

```bash
curl -s -o /dev/null -w "%{http_code}" http://178.105.128.174:8080/
```

Expected: `200`

- [ ] **Step 3: Confirm brain endpoint responds**

```bash
curl -s http://178.105.128.174:8080/api/brain | python3 -m json.tool | head -20
```

Expected: JSON with `nodes` and `links` arrays (may be empty on fresh deploy).

- [ ] **Step 4: Confirm SSE stream connects**

```bash
curl -N http://178.105.128.174:8080/api/events
```

Expected: prints `data: {"type": "heartbeat"}` within 1 second, then stays connected. Ctrl-C to stop.

- [ ] **Step 5: Open in browser and verify**

Navigate to `http://178.105.128.174:8080` in a browser. Verify:
- Header shows "CLAWBOT LTD", revenue, kill clock bar
- Five executive cards visible across the top
- Brain SVG area is present (may be empty until knowledge is written)
- Feed shows recent escalations from initial state load

- [ ] **Step 6: Watch a live executive cycle arrive**

Wait up to 10 minutes. When an executive cycle completes:
- The relevant card should flash cyan ("thinking") then settle to "success"
- A directive entry should appear in the feed
- If it included an escalation, that also appears

- [ ] **Step 7: Commit deploy confirmation note**

No code change — just confirm in conversation.

---

## Self-Review

**Spec coverage check:**
- ✅ Brain graph (force-directed D3) — Task 6
- ✅ Executive cards with live status — Task 6
- ✅ Activity feed (escalations + directives) — Task 6
- ✅ Kill clock — Task 6
- ✅ Revenue display — Task 6
- ✅ SSE real-time updates — Task 4
- ✅ cycle_start events for "thinking" state — Task 2
- ✅ Brain similarity links — Task 3
- ✅ Initial state load from metrics files — Task 4
- ✅ Port exposed and deploy instructions — Tasks 1 & 7

**Placeholder scan:** No TBD, TODO, or "add appropriate" phrases found.

**Type consistency:** `EventBroadcaster.broadcast(dict)` → called consistently. `compute_links(nodes: list[dict])` → used in `BrainCache.get()`. `start_dashboard(db_pool, redis_url)` → called from `main.py`. All consistent.
