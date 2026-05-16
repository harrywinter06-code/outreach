"""FastAPI dashboard server — EventBroadcaster, brain helpers, SSE, routes."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import time
from dataclasses import asdict
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
    "operator.escalation", "board.resolution", "brain.recall", "brain.write",
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


def _parse_directive_target(response_raw: str) -> str | None:
    """Extract the 'to' field from an executive's JSON directive, or None."""
    import re
    try:
        match = re.search(r"```(?:json)?\s*([\s\S]+?)```", response_raw)
        blob = match.group(1) if match else response_raw
        start, end = blob.find("{"), blob.rfind("}")
        if start != -1 and end != -1:
            data = json.loads(blob[start: end + 1])
            target = data.get("to")
            if isinstance(target, str) and target:
                return target.lower()
    except Exception:
        pass
    return None


def _build_flow_matrix(flow: dict[tuple[str, str], int]) -> dict[str, Any]:
    edges = sorted(
        [{"from": f, "to": t, "count": c} for (f, t), c in flow.items()],
        key=lambda e: e["count"],
        reverse=True,
    )
    return {"edges": edges, "total": sum(flow.values())}


def _build_spend_payload(spent_usd: float, max_usd: float) -> dict[str, Any]:
    pct = round(spent_usd / max_usd * 100, 1) if max_usd > 0 else 0.0
    return {"spent_usd": round(spent_usd, 4), "max_usd": max_usd, "pct": pct}


def _build_provider_health(name: str, rpm: int, max_rpm: int) -> dict[str, Any]:
    pct = round(rpm / max_rpm * 100, 1) if max_rpm > 0 else 0.0
    if rpm == 0:
        status = "idle"
    elif rpm >= max_rpm:
        status = "limit"
    elif pct >= 80:
        status = "busy"
    else:
        status = "ok"
    return {"name": name, "rpm": rpm, "max_rpm": max_rpm, "pct": pct, "status": status}


class SpendCache:
    """Reads today's LLM spend from Redis. Cached 5 s to avoid hammering Redis."""

    _TTL = 5.0
    _SPEND_KEY_PREFIX = "clawbot:spend"

    def __init__(self, redis_url: str, max_usd: float) -> None:
        self._url = redis_url
        self._max_usd = max_usd
        self._cached_at: float = 0.0
        self._data: dict[str, Any] = {"spent_usd": 0.0, "max_usd": max_usd, "pct": 0.0}

    async def get(self) -> dict[str, Any]:
        if time.monotonic() - self._cached_at < self._TTL:
            return self._data
        import redis.asyncio as aioredis
        r = await aioredis.from_url(self._url, decode_responses=True)
        try:
            today = datetime.now(UTC).strftime("%Y-%m-%d")
            val = await r.hget(f"{self._SPEND_KEY_PREFIX}:{today}", "usd_total")
            spent = float(val) if val else 0.0
            self._data = _build_spend_payload(spent, self._max_usd)
        except Exception as exc:
            logger.warning("SpendCache read failed: %s", exc)
        finally:
            await r.aclose()
        self._cached_at = time.monotonic()
        return self._data


class RevenueHistoryCache:
    """Fetches 14-day per-day GBP revenue from Gumroad. Cached 10 min."""

    _TTL = 600.0

    def __init__(self, gumroad_api_key: str) -> None:
        self._key = gumroad_api_key
        self._cached_at: float = 0.0
        self._data: list[dict[str, Any]] = []

    async def get(self) -> list[dict[str, Any]]:
        if time.monotonic() - self._cached_at < self._TTL:
            return self._data
        if not self._key:
            from datetime import timedelta
            today = date.today()
            self._data = [
                {"date": (today - timedelta(days=i)).isoformat(), "amount": 0.0}
                for i in range(13, -1, -1)
            ]
            self._cached_at = time.monotonic()
            return self._data
        try:
            from clawbot.gumroad import GumroadClient
            client = GumroadClient(api_key=self._key)
            by_day = await client.sales_by_day_gbp(days=14)
            self._data = [
                {"date": d, "amount": round(v, 2)}
                for d, v in sorted(by_day.items())
            ]
        except Exception as exc:
            logger.warning("RevenueHistoryCache fetch failed: %s", exc)
        self._cached_at = time.monotonic()
        return self._data


_PROVIDERS_TTL = 10.0


class ProvidersCache:
    def __init__(self, redis_url: str, providers: list[tuple[str, int]]) -> None:
        self._redis_url = redis_url
        self._providers = providers  # [(name, max_rpm)]
        self._cache: list[dict] | None = None
        self._fetched_at: float = 0.0

    async def get(self) -> list[dict]:
        if self._cache is not None and time.monotonic() - self._fetched_at < _PROVIDERS_TTL:
            return self._cache
        try:
            import redis.asyncio as aioredis
            r = await aioredis.from_url(self._redis_url, decode_responses=True)
            now_minute = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M")
            results = []
            for name, max_rpm in self._providers:
                key = f"clawbot:ratelimit:{name}:{now_minute}"
                val = await r.get(key)
                rpm = int(val) if val else 0
                results.append(_build_provider_health(name, rpm, max_rpm))
            await r.aclose()
            self._cache = results
            self._fetched_at = time.monotonic()
            return results
        except Exception:
            return self._cache or []


class RedisReader:
    """Tails watched Redis streams and fans events into the broadcaster."""

    def __init__(self, redis_url: str, broadcaster: EventBroadcaster) -> None:
        self._url = redis_url
        self._bc = broadcaster
        self._flow: dict[tuple[str, str], int] = {}
        self._last_responses: dict[str, str] = {}

    def get_flow(self) -> dict[str, Any]:
        return _build_flow_matrix(self._flow)

    def get_last_responses(self) -> dict[str, str]:
        return dict(self._last_responses)

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
            response_raw = payload.get("response", "")
            action = _extract_action(response_raw)
            target = _parse_directive_target(response_raw)
            if target:
                self._flow[(agent, target)] = self._flow.get((agent, target), 0) + 1
            if response_raw:
                self._last_responses[agent] = response_raw
            await self._bc.broadcast({
                "type": "cycle_complete",
                "agent": agent,
                "success": True,
                "action": action,
                "to": target or "",
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

        elif topic == "board.resolution":
            resolution_text = payload.get("resolution", payload.get("response", ""))
            await self._bc.broadcast({
                "type": "board_resolution",
                "resolution": resolution_text,
                "ts": payload.get("ts", ""),
            })
            log_path = _METRICS_DIR / "board_log.jsonl"
            entry = json.dumps({
                "resolution": resolution_text,
                "ts": payload.get("ts", ""),
                "logged_at": datetime.now(UTC).isoformat(),
            }) + "\n"
            try:
                with log_path.open("a", encoding="utf-8") as f:
                    f.write(entry)
            except Exception:
                pass

        elif topic == "brain.recall":
            await self._bc.broadcast({
                "type": "brain_recall",
                "node_ids": payload.get("node_ids", []),
                "ts": payload.get("ts", ""),
            })

        elif topic == "brain.write":
            await self._bc.broadcast({
                "type": "brain_write",
                "node_id": payload.get("node_id"),
                "category": payload.get("category", "decision"),
                "ts": payload.get("ts", ""),
            })


# ── FastAPI app ───────────────────────────────────────────────────────────────

_METRICS_DIR = Path("/metrics")
_FOUNDED = "2026-05-16"
_EXECUTIVES = ["ceo", "cfo", "cmo", "coo", "cto"]

_broadcaster: EventBroadcaster | None = None
_brain_cache: BrainCache | None = None
_reader: "RedisReader | None" = None
_spend_cache: SpendCache | None = None
_revenue_history_cache: RevenueHistoryCache | None = None
_providers_cache: ProvidersCache | None = None


def _provider_max_rpm(name: str, settings: Any) -> int:
    if name.startswith("nim"):
        return int(settings.nim_rpm)
    if name == "groq":
        return int(settings.groq_rpm)
    if name == "gemini":
        return int(settings.gemini_rpm)
    if name == "cerebras":
        return int(settings.cerebras_rpm)
    return 30


def create_app(db_pool: Any, redis_url: str) -> Any:
    global _broadcaster, _brain_cache, _spend_cache, _revenue_history_cache, _providers_cache
    from clawbot.config import settings
    _broadcaster = EventBroadcaster()
    _brain_cache = BrainCache(db_pool)
    _spend_cache = SpendCache(redis_url=redis_url, max_usd=settings.max_daily_spend_usd)
    _revenue_history_cache = RevenueHistoryCache(gumroad_api_key=settings.gumroad_api_key)
    provider_pairs = [(name, _provider_max_rpm(name, settings)) for name in settings.active_provider_names]
    _providers_cache = ProvidersCache(redis_url=redis_url, providers=provider_pairs)

    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles

    app = FastAPI(docs_url=None, redoc_url=None)

    _api_key = os.environ.get("DASHBOARD_API_KEY", "")
    if not _api_key:
        logger.warning("DASHBOARD_API_KEY not set — dashboard write endpoints are UNPROTECTED")

    def _require_key(request: Request) -> None:
        """Reject write/sensitive requests without a valid X-API-Key header."""
        if not _api_key:
            return  # unconfigured = local dev only; warned above
        provided = request.headers.get("X-API-Key", "")
        if not secrets.compare_digest(provided.encode(), _api_key.encode()):
            raise HTTPException(status_code=401, detail="Invalid API key")

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

    @app.get("/api/signals")
    async def signals() -> JSONResponse:
        feed_path = _METRICS_DIR / "opportunity_feed.json"
        if not feed_path.exists():
            return JSONResponse({"opportunities": [], "last_scan": ""})
        try:
            return JSONResponse(json.loads(feed_path.read_text(encoding="utf-8")))
        except Exception:
            return JSONResponse({"opportunities": [], "last_scan": ""})

    @app.get("/api/flow")
    async def flow() -> JSONResponse:
        if _reader is None:
            return JSONResponse({"edges": [], "total": 0})
        return JSONResponse(_reader.get_flow())

    @app.get("/api/spend")
    async def spend() -> JSONResponse:
        if _spend_cache is None:
            return JSONResponse({"spent_usd": 0.0, "max_usd": 5.0, "pct": 0.0})
        return JSONResponse(await _spend_cache.get())

    @app.get("/api/revenue_history")
    async def revenue_history() -> JSONResponse:
        if _revenue_history_cache is None:
            return JSONResponse([])
        return JSONResponse(await _revenue_history_cache.get())

    @app.post("/api/reply")
    async def reply(request: Request) -> JSONResponse:
        _require_key(request)
        from clawbot.bus import MessageBus
        body = await request.json()
        message = str(body.get("message", "")).strip()
        if not message:
            return JSONResponse({"ok": False, "error": "empty message"}, status_code=400)
        bus = MessageBus(redis_url=redis_url)
        await bus.connect()
        await bus.subscribe("operator.message")
        await bus.publish("operator.message", {
            "message": message,
            "ts": datetime.now(UTC).isoformat(),
            "source": "dashboard",
        })
        await bus.close()
        return JSONResponse({"ok": True})

    @app.post("/api/kill")
    async def kill_on(request: Request) -> JSONResponse:
        _require_key(request)
        kill_path = Path(os.environ.get("KILL_FILE_PATH", "/var/run/clawbot/clawbot.KILL"))
        kill_path.parent.mkdir(parents=True, exist_ok=True)
        kill_path.touch()
        return JSONResponse({"ok": True, "armed": True})

    @app.delete("/api/kill")
    async def kill_off(request: Request) -> JSONResponse:
        _require_key(request)
        kill_path = Path(os.environ.get("KILL_FILE_PATH", "/var/run/clawbot/clawbot.KILL"))
        if kill_path.exists():
            kill_path.unlink()
        return JSONResponse({"ok": True, "armed": False})

    @app.get("/api/strategy")
    async def strategy() -> JSONResponse:
        path = _METRICS_DIR / "strategy_log.json"
        if not path.exists():
            return JSONResponse({"current_strategy": "undefined", "days_active": 0,
                                 "pivot_count_this_month": 0})
        try:
            return JSONResponse(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            return JSONResponse({"current_strategy": "undefined", "days_active": 0,
                                 "pivot_count_this_month": 0})

    @app.get("/api/assets")
    async def assets() -> JSONResponse:
        path = _METRICS_DIR / "compounding_assets.json"
        if not path.exists():
            return JSONResponse({"email_subscribers": 0, "content_pieces_published": 0,
                                 "returning_customers": 0, "social_following": 0})
        try:
            return JSONResponse(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            return JSONResponse({"email_subscribers": 0, "content_pieces_published": 0,
                                 "returning_customers": 0, "social_following": 0})

    @app.get("/api/providers")
    async def providers() -> JSONResponse:
        if _providers_cache is None:
            return JSONResponse({"providers": []})
        return JSONResponse({"providers": await _providers_cache.get()})

    @app.get("/api/directives")
    async def directives(request: Request) -> JSONResponse:
        _require_key(request)
        if _reader is None:
            return JSONResponse({"responses": {}})
        return JSONResponse({"responses": _reader.get_last_responses()})

    @app.get("/api/board_log")
    async def board_log() -> JSONResponse:
        path = _METRICS_DIR / "board_log.jsonl"
        if not path.exists():
            return JSONResponse({"entries": []})
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        entries = []
        for line in lines[-50:]:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        return JSONResponse({"entries": list(reversed(entries))})

    @app.get("/api/widgets")
    async def widgets() -> JSONResponse:
        from clawbot.metrics import MetricsStore
        store = MetricsStore()
        return JSONResponse({"widgets": [asdict(w) for w in store.get_widgets()]})

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
    global _reader
    import uvicorn

    app = create_app(db_pool=db_pool, redis_url=redis_url)
    assert _broadcaster is not None
    reader = RedisReader(redis_url=redis_url, broadcaster=_broadcaster)
    _reader = reader

    config = uvicorn.Config(app, host="127.0.0.1", port=8080, log_level="warning", access_log=False)
    server = uvicorn.Server(config)

    await asyncio.gather(server.serve(), reader.run_forever())
