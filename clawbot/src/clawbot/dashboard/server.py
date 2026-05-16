"""FastAPI dashboard server — EventBroadcaster, brain helpers, SSE, routes."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, UTC, date
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# ── EventBroadcaster ────────────────────────────────────────────────────────


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


# ── Brain helpers ────────────────────────────────────────────────────────────


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
                links.append({
                    "source": nodes[i]["id"],
                    "target": nodes[j]["id"],
                    "strength": round(s, 3),
                })
    return links


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
        for n in nodes:
            del n["embedding"]
        self._data = {"nodes": nodes, "links": links}
        self._cached_at = time.monotonic()
        return self._data


# ── Redis stream reader ───────────────────────────────────────────────────────

WATCHED_STREAMS = [
    "ceo.cycle_start", "cfo.cycle_start", "cmo.cycle_start", "coo.cycle_start", "cto.cycle_start",
    "ceo.directive",   "cfo.directive",   "cmo.directive",   "coo.directive",   "cto.directive",
    "operator.escalation",
]
_STREAM_PREFIX = "clawbot:bus"


def _extract_action(response_raw: str) -> str:
    """Pull action text from LLM JSON response, falling back to raw truncated text."""
    import re
    try:
        match = re.search(r"```(?:json)?\s*([\s\S]+?)```", response_raw)
        blob = match.group(1) if match else response_raw
        start, end = blob.find("{"), blob.rfind("}")
        if start != -1 and end != -1:
            data = json.loads(blob[start: end + 1])
            return str(data.get("action") or data.get("directive") or "")[:200]
    except Exception:
        pass
    return response_raw[:200]


class RedisReader:
    """Tails watched Redis streams and fans events into the broadcaster."""

    def __init__(self, redis_url: str, broadcaster: EventBroadcaster) -> None:
        self._url = redis_url
        self._bc = broadcaster

    async def run_forever(self) -> None:
        import redis.asyncio as aioredis
        r = await aioredis.from_url(self._url, decode_responses=True)
        stream_keys = {f"{_STREAM_PREFIX}:{t}": t for t in WATCHED_STREAMS}
        last_ids: dict[str, str] = {k: "$" for k in stream_keys}
        while True:
            try:
                results = await r.xread(last_ids, count=20, block=1000)
                for stream_key, messages in (results or []):
                    topic = stream_keys.get(stream_key, stream_key)
                    for msg_id, fields in messages:
                        last_ids[stream_key] = msg_id
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
            action = _extract_action(payload.get("response", ""))
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


# ── FastAPI app ───────────────────────────────────────────────────────────────

_METRICS_DIR = Path("/metrics")
_FOUNDED = "2026-05-16"
_EXECUTIVES = ["ceo", "cfo", "cmo", "coo", "cto"]

_broadcaster: EventBroadcaster | None = None
_brain_cache: BrainCache | None = None


def create_app(db_pool: Any, redis_url: str) -> Any:
    global _broadcaster, _brain_cache
    _broadcaster = EventBroadcaster()
    _brain_cache = BrainCache(db_pool)

    from fastapi import FastAPI, Request
    from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles

    app = FastAPI(docs_url=None, redoc_url=None)

    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        return HTMLResponse((static_dir / "index.html").read_text(encoding="utf-8"))

    @app.get("/api/brain")
    async def brain() -> JSONResponse:
        assert _brain_cache is not None
        data = await _brain_cache.get()
        return JSONResponse(data)

    @app.get("/api/state")
    async def state() -> JSONResponse:
        return JSONResponse(_build_state_snapshot())

    @app.get("/api/events")
    async def events(request: Request) -> StreamingResponse:
        assert _broadcaster is not None

        async def generate():
            q = _broadcaster.subscribe()
            try:
                yield 'data: {"type": "heartbeat"}\n\n'
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        data = await asyncio.wait_for(q.get(), timeout=15.0)
                        yield f"data: {data}\n\n"
                    except asyncio.TimeoutError:
                        yield 'data: {"type": "heartbeat"}\n\n'
            finally:
                _broadcaster.unsubscribe(q)

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app


def _build_state_snapshot() -> dict[str, Any]:
    agents: dict[str, Any] = {}
    for agent_id in _EXECUTIVES:
        obs_path = _METRICS_DIR / agent_id / "observations.jsonl"
        cycles: list[bool] = []
        last_action = ""
        if obs_path.exists():
            for line in obs_path.read_text(encoding="utf-8").splitlines()[-20:]:
                try:
                    entry = json.loads(line)
                    cycles.append(bool(entry.get("success", False)))
                    if entry.get("success"):
                        last_action = entry.get("summary", last_action)
                except Exception:
                    pass
        agents[agent_id] = {"status": "idle", "cycles": cycles[-10:], "last_action": last_action}

    revenue = 0.0
    metrics_path = _METRICS_DIR / "company_metrics.json"
    if metrics_path.exists():
        try:
            revenue = json.loads(metrics_path.read_text())["revenue_7d_gbp"]
        except Exception:
            pass

    escalations: list[dict] = []
    esc_path = _METRICS_DIR / "escalations.jsonl"
    if esc_path.exists():
        for line in esc_path.read_text(encoding="utf-8").splitlines()[-20:]:
            try:
                escalations.append(json.loads(line))
            except Exception:
                pass

    day = (date.today() - date.fromisoformat(_FOUNDED)).days + 1

    return {
        "agents": agents,
        "metrics": {"revenue_7d_gbp": revenue},
        "kill_clock": {"day": day, "founded": _FOUNDED, "max_days": 60},
        "recent_escalations": escalations[-15:],
    }


async def start_dashboard(db_pool: Any, redis_url: str) -> None:
    """Launch FastAPI + background Redis reader as asyncio tasks."""
    import uvicorn

    app = create_app(db_pool=db_pool, redis_url=redis_url)
    assert _broadcaster is not None
    reader = RedisReader(redis_url=redis_url, broadcaster=_broadcaster)

    config = uvicorn.Config(app, host="0.0.0.0", port=8080, log_level="warning", access_log=False)
    server = uvicorn.Server(config)

    await asyncio.gather(server.serve(), reader.run_forever())
