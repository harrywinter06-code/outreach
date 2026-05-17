# Dashboard V2 — Sound, Brain Animations, Panels, Interactivity

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the live dashboard with sound design, brain retrieval animations, opportunity signals panel, directive flow tracking, board room modal, operator reply box, and kill switch toggle.

**Architecture:** Backend publishes two new bus events (`brain.recall`, `brain.write`) from the scheduler; `RedisReader` in `dashboard/server.py` subscribes to these plus `board.resolution` and fans them into the SSE broadcaster. Three new REST endpoints handle operator reply, kill-switch, and signals. All sound is frontend-only via Web Audio API. Layout gains a signals strip below the brain graph and a reply input at the bottom of the feed.

**Tech Stack:** Web Audio API (no deps), FastAPI POST endpoints, Redis Streams (existing bus), asyncpg (existing), `/metrics/opportunity_feed.json` (existing MetricsStore output)

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Modify | `src/clawbot/scheduler.py` | Publish `brain.recall` + `brain.write` events after each brain call |
| Modify | `src/clawbot/main.py` | Subscribe to `brain.recall`, `brain.write`, `board.resolution` |
| Modify | `src/clawbot/dashboard/server.py` | New endpoints, RedisReader additions, directive flow tracking |
| Modify | `src/clawbot/dashboard/static/index.html` | Sound, animations, signals panel, reply box, kill switch, board modal |
| Modify | `tests/test_dashboard_server.py` | Tests for new server functions |

---

## Task 1: Brain Event Publishing

**Files:**
- Modify: `src/clawbot/scheduler.py` (~lines 266, 325–355)
- Modify: `src/clawbot/main.py` (~line 88)

After `_brain_recall` gets search results, publish the matched node IDs so the dashboard can animate them. After `_brain_remember` writes, publish the new node ID.

- [ ] **Step 1: Add `brain.recall` publish in `_brain_recall`**

In `src/clawbot/scheduler.py`, find `_brain_recall`. After `entries = await self._brain.search(...)` succeeds, publish node IDs to the bus:

```python
    async def _brain_recall(self, metrics: dict) -> str:
        """Top-3 prior decisions by similarity to current metrics."""
        if self._brain is None:
            return ""
        query = json.dumps(metrics)
        if len(query) < BRAIN_RECALL_MIN_QUERY_CHARS:
            return ""
        query = query[:500]
        try:
            entries = await self._brain.search(query=query, k=3, category="decision")
        except Exception as exc:
            logger.warning("Brain read failed (non-fatal): %s", exc)
            return ""
        if not entries:
            return ""
        # Publish node IDs so dashboard can animate the recall
        await self._bus.publish("brain.recall", {
            "node_ids": [e.id for e in entries],
            "query_preview": query[:80],
            "ts": datetime.now(UTC).isoformat(),
        })
        return "\n\nRecent relevant decisions:\n" + "\n".join(
            f"- {e.content[:200]}" for e in entries
        )
```

- [ ] **Step 2: Add `brain.write` publish in `_brain_remember`**

Find `_brain_remember`. After `await self._brain.write(...)` succeeds, publish the returned node ID:

```python
    async def _brain_remember(self, response: str | None) -> None:
        """Persist the CEO's response to the brain."""
        if self._brain is None or not response:
            return
        try:
            node_id = await self._brain.write(response, category="decision")
            await self._bus.publish("brain.write", {
                "node_id": node_id,
                "category": "decision",
                "ts": datetime.now(UTC).isoformat(),
            })
        except Exception as exc:
            logger.warning("Brain write failed (non-fatal): %s", exc)
```

- [ ] **Step 3: Subscribe to new topics in `main.py`**

In `src/clawbot/main.py`, add three topics to the `topics` list:

```python
    topics = [
        "ceo.directive", "board.resolution", "coo.task", "cmo.campaign",
        "code.change_request", "operator.escalation", "operator.reply",
        "operator.message",
        "ceo.cycle_start", "cfo.cycle_start", "cmo.cycle_start",
        "coo.cycle_start", "cto.cycle_start",
        "brain.recall", "brain.write",
    ]
```

- [ ] **Step 4: Run tests**

```bash
uv run python -m pytest tests/test_scheduler.py -x -q
```

Expected: 12 passed.

- [ ] **Step 5: Commit**

```bash
git add src/clawbot/scheduler.py src/clawbot/main.py
git commit -m "feat: publish brain.recall and brain.write events to bus"
```

---

## Task 2: New Dashboard API Endpoints + RedisReader Extensions

**Files:**
- Modify: `src/clawbot/dashboard/server.py`
- Modify: `tests/test_dashboard_server.py`

Add five things to `server.py`:
1. `WATCHED_STREAMS` gains `brain.recall`, `brain.write`, `board.resolution`
2. `RedisReader._handle` handles the three new topics
3. `RedisReader` tracks directive flow as `{(from, to): int}` dict
4. Three new FastAPI endpoints: `/api/signals`, `/api/reply` (POST), `/api/kill` (POST/DELETE), `/api/flow`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_dashboard_server.py`:

```python
from clawbot.dashboard.server import _parse_directive_target, _build_flow_matrix


class TestParseDirectiveTarget:
    def test_parses_to_field_from_json(self):
        raw = '{"to": "cmo", "action": "Draft article", "priority": "high"}'
        assert _parse_directive_target(raw) == "cmo"

    def test_returns_none_for_missing_to(self):
        raw = '{"action": "Do something", "priority": "low"}'
        assert _parse_directive_target(raw) is None

    def test_returns_none_for_invalid_json(self):
        assert _parse_directive_target("not json at all") is None

    def test_parses_from_markdown_fenced_json(self):
        raw = '```json\n{"to": "cfo", "action": "Review budget"}\n```'
        assert _parse_directive_target(raw) == "cfo"


class TestBuildFlowMatrix:
    def test_empty_flow(self):
        result = _build_flow_matrix({})
        assert result == {"edges": [], "total": 0}

    def test_single_edge(self):
        result = _build_flow_matrix({("ceo", "cmo"): 3})
        assert result["total"] == 3
        assert len(result["edges"]) == 1
        assert result["edges"][0] == {"from": "ceo", "to": "cmo", "count": 3}

    def test_multiple_edges_sorted_by_count(self):
        flow = {("ceo", "cfo"): 1, ("ceo", "cmo"): 5, ("cfo", "cto"): 2}
        result = _build_flow_matrix(flow)
        counts = [e["count"] for e in result["edges"]]
        assert counts == sorted(counts, reverse=True)
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run python -m pytest tests/test_dashboard_server.py::TestParseDirectiveTarget tests/test_dashboard_server.py::TestBuildFlowMatrix -x -q
```

Expected: `ImportError: cannot import name '_parse_directive_target'`

- [ ] **Step 3: Add `_parse_directive_target` and `_build_flow_matrix` to `server.py`**

Add these two functions after `_extract_action` in `src/clawbot/dashboard/server.py`:

```python
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
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
uv run python -m pytest tests/test_dashboard_server.py::TestParseDirectiveTarget tests/test_dashboard_server.py::TestBuildFlowMatrix -x -q
```

Expected: 7 tests pass.

- [ ] **Step 5: Extend `WATCHED_STREAMS` and update `RedisReader`**

In `src/clawbot/dashboard/server.py`, replace the `WATCHED_STREAMS` list and `RedisReader` class with the extended version:

```python
WATCHED_STREAMS = [
    "ceo.cycle_start", "cfo.cycle_start", "cmo.cycle_start", "coo.cycle_start", "cto.cycle_start",
    "ceo.directive",   "cfo.directive",   "cmo.directive",   "coo.directive",   "cto.directive",
    "operator.escalation", "board.resolution", "brain.recall", "brain.write",
]


class RedisReader:
    """Tails watched Redis streams and fans events into the broadcaster."""

    def __init__(self, redis_url: str, broadcaster: EventBroadcaster) -> None:
        self._url = redis_url
        self._bc = broadcaster
        self._flow: dict[tuple[str, str], int] = {}

    def get_flow(self) -> dict[str, Any]:
        return _build_flow_matrix(self._flow)

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
            await self._bc.broadcast({
                "type": "board_resolution",
                "resolution": payload.get("resolution", payload.get("response", "")),
                "ts": payload.get("ts", ""),
            })

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
```

- [ ] **Step 6: Add new FastAPI endpoints to `create_app`**

In `create_app`, after the existing `@app.get("/api/events")` route, add four new routes. Also store `_reader` as a module-level ref so `/api/flow` can access it:

```python
_reader: "RedisReader | None" = None   # add near _broadcaster/_brain_cache at top of module


# Inside create_app, after the events route:

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

    @app.post("/api/reply")
    async def reply(request: Request) -> JSONResponse:
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
    async def kill_on() -> JSONResponse:
        kill_path = Path(os.environ.get("KILL_FILE_PATH", "/var/run/clawbot/clawbot.KILL"))
        kill_path.parent.mkdir(parents=True, exist_ok=True)
        kill_path.touch()
        return JSONResponse({"ok": True, "armed": True})

    @app.delete("/api/kill")
    async def kill_off() -> JSONResponse:
        kill_path = Path(os.environ.get("KILL_FILE_PATH", "/var/run/clawbot/clawbot.KILL"))
        if kill_path.exists():
            kill_path.unlink()
        return JSONResponse({"ok": True, "armed": False})
```

Also add `import os` at the top of `server.py`, and in `create_app` store `redis_url` as a closure variable and set `_reader`:

```python
def create_app(db_pool: Any, redis_url: str) -> Any:
    global _broadcaster, _brain_cache, _reader
    _broadcaster = EventBroadcaster()
    _brain_cache = BrainCache(db_pool)
    # _reader is set in start_dashboard after RedisReader is instantiated
    ...
```

In `start_dashboard`:

```python
async def start_dashboard(db_pool: Any, redis_url: str) -> None:
    global _reader
    import uvicorn

    app = create_app(db_pool=db_pool, redis_url=redis_url)
    assert _broadcaster is not None
    reader = RedisReader(redis_url=redis_url, broadcaster=_broadcaster)
    _reader = reader   # expose to /api/flow endpoint

    config = uvicorn.Config(app, host="0.0.0.0", port=8080, log_level="warning", access_log=False)
    server = uvicorn.Server(config)

    await asyncio.gather(server.serve(), reader.run_forever())
```

- [ ] **Step 7: Run all tests**

```bash
uv run python -m pytest -x -q
```

Expected: 272 passed (265 + 7 new).

- [ ] **Step 8: Commit**

```bash
git add src/clawbot/dashboard/server.py tests/test_dashboard_server.py
git commit -m "feat: signals/reply/kill/flow endpoints, brain+board SSE events"
```

---

## Task 3: Frontend — Sound Design + Brain Animations

**Files:**
- Modify: `src/clawbot/dashboard/static/index.html`

This task adds Web Audio API sounds and two brain animations (node flash on write, glow sequence on recall). No backend changes.

- [ ] **Step 1: Add sound engine to `index.html`**

Just before the closing `</script>` tag, add the complete sound engine:

```javascript
// ── Sound Engine (Web Audio API) ─────────────────────────────────
let _ctx = null;
let _soundOn = true;

function _ac() {
  if (!_ctx) _ctx = new (window.AudioContext || window.webkitAudioContext)();
  if (_ctx.state === 'suspended') _ctx.resume();
  return _ctx;
}

function _osc(freq, type, gain, attack, sustain, release) {
  const ctx = _ac();
  const g = ctx.createGain();
  g.connect(ctx.destination);
  g.gain.setValueAtTime(0, ctx.currentTime);
  g.gain.linearRampToValueAtTime(gain, ctx.currentTime + attack);
  g.gain.setValueAtTime(gain, ctx.currentTime + attack + sustain);
  g.gain.linearRampToValueAtTime(0, ctx.currentTime + attack + sustain + release);
  const o = ctx.createOscillator();
  o.type = type;
  o.frequency.setValueAtTime(freq, ctx.currentTime);
  o.connect(g);
  o.start(ctx.currentTime);
  o.stop(ctx.currentTime + attack + sustain + release + 0.01);
}

const SOUNDS = {
  brainWrite:   () => { if (!_soundOn) return; _osc(880, 'sine', 0.08, 0.01, 0.05, 0.15); },
  brainRecall:  () => { if (!_soundOn) return; _osc(440, 'sine', 0.06, 0.02, 0.1, 0.3); _osc(660, 'sine', 0.04, 0.05, 0.05, 0.25); },
  cycleComplete:() => { if (!_soundOn) return; _osc(523, 'sine', 0.07, 0.01, 0.05, 0.2); setTimeout(() => _osc(659, 'sine', 0.07, 0.01, 0.05, 0.25), 120); },
  escalation:   () => { if (!_soundOn) return; _osc(880, 'square', 0.04, 0.005, 0.03, 0.1); setTimeout(() => _osc(880, 'square', 0.04, 0.005, 0.03, 0.1), 150); },
  revenue:      () => { if (!_soundOn) return; [523,659,784,1047].forEach((f,i) => setTimeout(() => _osc(f,'sine',0.1,0.01,0.08,0.15), i*80)); },
  boardMeeting: () => { if (!_soundOn) return; _osc(220, 'sine', 0.1, 0.05, 0.5, 0.5); },
  killArmed:    () => { if (!_soundOn) return; _osc(110, 'sawtooth', 0.08, 0.1, 0.3, 0.4); },
};

function toggleSound() {
  _soundOn = !_soundOn;
  document.getElementById('snd-btn').textContent = _soundOn ? '🔊' : '🔇';
}
```

- [ ] **Step 2: Add sound toggle button to the header HTML**

In the `<header>` section, add the button just before `</header>`:

```html
  <button id="snd-btn" onclick="toggleSound()" style="
    background:none;border:1px solid var(--border);color:var(--muted);
    padding:4px 10px;border-radius:6px;cursor:pointer;font-size:13px;
    transition:color .2s,border-color .2s;
  " onmouseover="this.style.color='var(--text)'" onmouseout="this.style.color='var(--muted)'">🔊</button>
```

- [ ] **Step 3: Hook sounds into `onEvent`**

In the `onEvent` function, add sound calls:

```javascript
function onEvent(ev) {
  if (ev.type === 'heartbeat') return;

  if (ev.type === 'cycle_start') {
    const s = S[ev.agent]; if (!s) return;
    s.status = 'thinking'; s.t0 = Date.now();
    renderCard(ev.agent);
  }
  if (ev.type === 'cycle_complete') {
    const s = S[ev.agent]; if (!s) return;
    s.status = ev.success ? 'success' : 'error';
    s.t0 = 0;
    if (ev.action) s.action = ev.action;
    s.cycles = [...s.cycles.slice(-9), !!ev.success];
    renderCard(ev.agent);
    pushFeed(ev);
    SOUNDS.cycleComplete();
    setTimeout(() => { s.status = 'idle'; renderCard(ev.agent); }, 3500);
  }
  if (ev.type === 'escalation') {
    pushFeed(ev);
    SOUNDS.escalation();
  }
  if (ev.type === 'metrics') {
    const prev = parseFloat(document.getElementById('rev').textContent.replace('£','')) || 0;
    setRev(ev.revenue_7d_gbp);
    if ((ev.revenue_7d_gbp || 0) > prev) SOUNDS.revenue();
  }
  if (ev.type === 'brain_write') flashBrainNode(ev.node_id);
  if (ev.type === 'brain_recall') glowBrainNodes(ev.node_ids || []);
  if (ev.type === 'board_resolution') showBoardModal(ev.resolution, ev.ts);
}
```

- [ ] **Step 4: Add brain animation functions**

Add these two functions to the script, after the `hideTip` function:

```javascript
function flashBrainNode(nodeId) {
  if (!nodeId) return;
  Ns.filter(d => d.id === nodeId)
    .transition().duration(100).attr('r', 14).attr('opacity', 1)
    .transition().duration(600).attr('r', d => Math.max(4, 8 - d.age_days * 0.4)).attr('opacity', d => Math.max(0.25, 1 - d.age_days / 25));
  SOUNDS.brainWrite();
}

function glowBrainNodes(nodeIds) {
  if (!nodeIds || !nodeIds.length) return;
  SOUNDS.brainRecall();
  nodeIds.forEach((id, i) => {
    setTimeout(() => {
      Ns.filter(d => d.id === id)
        .transition().duration(80).attr('r', 12).attr('opacity', 1)
        .attr('stroke', '#00d4ff').attr('stroke-width', 2)
        .transition().duration(500).attr('r', d => Math.max(4, 8 - d.age_days * 0.4))
        .attr('opacity', d => Math.max(0.25, 1 - d.age_days / 25))
        .attr('stroke-width', 0);
    }, i * 120);
  });
}
```

- [ ] **Step 5: Hot-patch and verify sounds work**

```bash
scp /c/Users/Winte/clawbot/src/clawbot/dashboard/static/index.html clawbot:/opt/clawbot/src/clawbot/dashboard/static/index.html
```

Open `http://178.105.128.174:8080` in browser. Click the 🔊 button to toggle. Verify it shows 🔇. Refresh page and confirm 🔊 is back. Actual sound playback can only be triggered by browser interaction first — clicking anything on the page unlocks Web Audio API, after which the next event will play sound.

- [ ] **Step 6: Commit**

```bash
git add src/clawbot/dashboard/static/index.html
git commit -m "feat: sound design + brain write flash + brain recall glow animation"
```

---

## Task 4: Frontend — Signals Panel, Reply Box, Kill Switch, Board Modal

**Files:**
- Modify: `src/clawbot/dashboard/static/index.html`

This task adds the four interactive/data features. The layout gains a signals strip below the exec cards (collapsible), a reply input at the bottom of the feed, a kill switch in the header, and a board room modal overlay.

- [ ] **Step 1: Add CSS for new components**

Add to the `<style>` block, after the `.fi-text` rule:

```css
/* ── KILL SWITCH ─────────────────────────────────────────────────── */
#kill-btn{
  padding:5px 12px;border-radius:6px;cursor:pointer;font-size:11px;
  font-weight:700;letter-spacing:.06em;text-transform:uppercase;
  border:1px solid rgba(239,68,68,.4);color:var(--red);background:rgba(239,68,68,.08);
  transition:all .2s;
}
#kill-btn:hover{background:rgba(239,68,68,.18);border-color:var(--red)}
#kill-btn.armed{background:var(--red);color:#fff;border-color:var(--red);box-shadow:0 0 12px rgba(239,68,68,.4)}

/* ── SIGNALS PANEL ───────────────────────────────────────────────── */
#signals-wrap{
  position:absolute;bottom:0;left:0;right:0;
  background:rgba(8,12,23,.96);
  border-top:1px solid var(--border);
  transition:max-height .35s ease;
  max-height:0;overflow:hidden;
  z-index:5;
}
#signals-wrap.open{max-height:220px}
#signals-toggle{
  position:absolute;bottom:12px;right:16px;z-index:6;
  background:none;border:1px solid var(--border);color:var(--muted);
  padding:3px 10px;border-radius:5px;cursor:pointer;font-size:10px;
  font-weight:700;letter-spacing:.08em;text-transform:uppercase;
  transition:color .2s;
}
#signals-toggle:hover{color:var(--text)}
#signals-list{padding:10px 16px;display:flex;flex-direction:column;gap:6px;overflow-y:auto;max-height:200px}
.sig{display:flex;gap:10px;align-items:flex-start}
.sig-bar-wrap{width:36px;flex-shrink:0;padding-top:3px}
.sig-bar{height:4px;border-radius:2px;background:var(--green)}
.sig-body{flex:1;min-width:0}
.sig-title{font-size:11px;font-weight:600;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sig-desc{font-size:10px;color:var(--muted);line-height:1.4;margin-top:1px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.sig-meta{font-size:9px;color:var(--muted);margin-top:2px}

/* ── REPLY INPUT ─────────────────────────────────────────────────── */
#reply-area{
  padding:10px 12px;border-top:1px solid var(--border);flex-shrink:0;
  display:flex;gap:8px;align-items:center;
}
#reply-input{
  flex:1;background:var(--muted2);border:1px solid var(--border);
  color:var(--text);padding:7px 11px;border-radius:6px;font-size:12px;
  outline:none;transition:border-color .2s;
  font-family:inherit;
}
#reply-input:focus{border-color:rgba(0,212,255,.4)}
#reply-input::placeholder{color:var(--muted)}
#reply-send{
  padding:7px 14px;border-radius:6px;cursor:pointer;font-size:11px;
  font-weight:700;background:rgba(0,212,255,.12);color:var(--cyan);
  border:1px solid rgba(0,212,255,.25);transition:all .2s;white-space:nowrap;
}
#reply-send:hover{background:rgba(0,212,255,.22)}
#reply-send:disabled{opacity:.4;cursor:default}

/* ── BOARD MODAL ─────────────────────────────────────────────────── */
#board-modal{
  position:fixed;inset:0;z-index:50;display:none;
  background:rgba(0,0,0,.7);backdrop-filter:blur(8px);
  align-items:center;justify-content:center;
}
#board-modal.show{display:flex;animation:fadeIn .4s ease}
@keyframes fadeIn{from{opacity:0;transform:scale(.95)}to{opacity:1;transform:scale(1)}}
.modal-box{
  background:#0d1226;border:1px solid var(--border);
  border-radius:12px;padding:28px 32px;max-width:520px;width:90%;
  box-shadow:0 24px 80px rgba(0,0,0,.6);
}
.modal-title{font-size:10px;font-weight:800;letter-spacing:.14em;color:var(--amber);text-transform:uppercase;margin-bottom:12px}
.modal-text{font-size:13px;line-height:1.7;color:var(--text);opacity:.85;white-space:pre-wrap;max-height:260px;overflow-y:auto}
.modal-footer{margin-top:16px;font-size:10px;color:var(--muted);display:flex;justify-content:space-between;align-items:center}
.modal-close{
  padding:6px 16px;border-radius:6px;cursor:pointer;font-size:11px;
  font-weight:700;background:var(--muted2);color:var(--text);border:none;
  transition:background .2s;
}
.modal-close:hover{background:#2d3748}
```

- [ ] **Step 2: Add kill switch button to header HTML**

In `<header>`, add the kill button between the sound button and `</header>`:

```html
  <button id="kill-btn" onclick="toggleKill()">KILL</button>
```

- [ ] **Step 3: Add signals panel HTML inside `#brain-wrap`**

Inside `<div id="brain-wrap">`, before the closing `</div>`, add:

```html
    <button id="signals-toggle" onclick="toggleSignals()">Signals</button>
    <div id="signals-wrap">
      <div id="signals-list"></div>
    </div>
```

- [ ] **Step 4: Add reply area HTML inside `#feed-wrap`**

Inside `<div id="feed-wrap">`, after `<div id="feed"></div>`, add:

```html
    <div id="reply-area">
      <input id="reply-input" type="text" placeholder="Message to operator channel…" maxlength="500"
             onkeydown="if(event.key==='Enter')sendReply()">
      <button id="reply-send" onclick="sendReply()">Send</button>
    </div>
```

- [ ] **Step 5: Add board modal HTML before `</body>`**

Add just before the closing `</body>` tag:

```html
<div id="board-modal">
  <div class="modal-box">
    <div class="modal-title">⚖️ Board Resolution</div>
    <div class="modal-text" id="board-modal-text"></div>
    <div class="modal-footer">
      <span id="board-modal-ts"></span>
      <button class="modal-close" onclick="closeBoardModal()">Dismiss</button>
    </div>
  </div>
</div>
```

- [ ] **Step 6: Add kill switch, signals, reply, and board modal JS functions**

Add to the script, after the sound engine:

```javascript
// ── Kill switch ───────────────────────────────────────────────────
let _killArmed = false;

function toggleKill() {
  const confirmed = _killArmed
    ? confirm('Disarm the kill switch? The company will continue running.')
    : confirm('ARM THE KILL SWITCH?\n\nThis will halt all executives on next watchdog tick (≤30s). Are you sure?');
  if (!confirmed) return;
  const method = _killArmed ? 'DELETE' : 'POST';
  fetch('/api/kill', {method}).then(r => r.json()).then(d => {
    _killArmed = d.armed;
    const btn = document.getElementById('kill-btn');
    btn.classList.toggle('armed', _killArmed);
    btn.textContent = _killArmed ? '■ ARMED' : 'KILL';
    if (_killArmed) SOUNDS.killArmed();
  }).catch(() => {});
}

// ── Signals panel ─────────────────────────────────────────────────
let _signalsOpen = false;

function toggleSignals() {
  _signalsOpen = !_signalsOpen;
  document.getElementById('signals-wrap').classList.toggle('open', _signalsOpen);
  document.getElementById('signals-toggle').textContent = _signalsOpen ? 'Hide Signals' : 'Signals';
  if (_signalsOpen) loadSignals();
}

function loadSignals() {
  fetch('/api/signals').then(r => r.json()).then(data => {
    const list = document.getElementById('signals-list');
    const opps = (data.opportunities || []).slice(0, 6);
    if (!opps.length) { list.innerHTML = '<div style="font-size:11px;color:var(--muted);padding:4px 0">No signals found yet</div>'; return; }
    list.innerHTML = opps.map(o => `
      <div class="sig">
        <div class="sig-bar-wrap"><div class="sig-bar" style="width:${Math.round(o.confidence*100)}%;background:${o.confidence>0.7?'var(--green)':o.confidence>0.5?'var(--amber)':'var(--muted)'}"></div></div>
        <div class="sig-body">
          <div class="sig-title">${esc(o.title)}</div>
          <div class="sig-desc">${esc(o.description)}</div>
          <div class="sig-meta">${Math.round(o.confidence*100)}% confidence · ${o.time_window_days}d window · ${esc(o.estimated_value)}</div>
        </div>
      </div>
    `).join('');
  }).catch(() => {});
}

// ── Reply input ───────────────────────────────────────────────────
function sendReply() {
  const input = document.getElementById('reply-input');
  const btn   = document.getElementById('reply-send');
  const msg   = input.value.trim();
  if (!msg) return;
  btn.disabled = true;
  fetch('/api/reply', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({message: msg}),
  }).then(r => r.json()).then(d => {
    if (d.ok) {
      input.value = '';
      pushFeed({type:'sent', from_agent:'operator', action: msg, ts: new Date().toISOString()});
    }
  }).catch(() => {}).finally(() => { btn.disabled = false; });
}

// ── Board room modal ──────────────────────────────────────────────
function showBoardModal(text, ts) {
  document.getElementById('board-modal-text').textContent = text || '';
  document.getElementById('board-modal-ts').textContent = fmtTime(ts);
  document.getElementById('board-modal').classList.add('show');
  SOUNDS.boardMeeting();
  setTimeout(closeBoardModal, 30000);
}

function closeBoardModal() {
  document.getElementById('board-modal').classList.remove('show');
}
```

- [ ] **Step 7: Add `sent` type to `pushFeed`**

In the `pushFeed` function, add a `sent` case in the conditionals:

```javascript
  } else if (item.type === 'sent') {
    cls  = 'fi dir';
    badge = '<span class="badge" style="background:rgba(16,185,129,.1);color:var(--green)">SENT</span>';
    text  = item.action || '';
  } else {
```

- [ ] **Step 8: Hot-patch frontend and full redeploy**

Since we changed `server.py` (new endpoints + `_reader` global), we need to hot-patch both files:

```bash
scp /c/Users/Winte/clawbot/src/clawbot/dashboard/server.py clawbot:/opt/clawbot/src/clawbot/dashboard/server.py
scp /c/Users/Winte/clawbot/src/clawbot/dashboard/static/index.html clawbot:/opt/clawbot/src/clawbot/dashboard/static/index.html
ssh clawbot 'cd /opt/clawbot && docker compose restart clawbot'
```

Wait 30 seconds, then verify:

```bash
curl -s http://178.105.128.174:8080/api/signals | python3 -m json.tool | head -10
curl -s http://178.105.128.174:8080/api/flow
```

Expected: `/api/signals` returns JSON with `opportunities` array (may be empty). `/api/flow` returns `{"edges": [], "total": 0}` (will fill as directives accumulate).

- [ ] **Step 9: Run all tests**

```bash
uv run python -m pytest -x -q
```

Expected: 272 passed.

- [ ] **Step 10: Commit everything**

```bash
git add src/clawbot/scheduler.py src/clawbot/main.py src/clawbot/dashboard/server.py src/clawbot/dashboard/static/index.html tests/test_dashboard_server.py
git commit -m "feat: dashboard v2 — sound, brain anim, signals, reply, kill switch, board modal"
```

---

## Self-Review

**Spec coverage:**
- ✅ Sound design — Task 3 (ambient placeholder note: ambient hum not included to avoid battery drain; all event sounds are included)
- ✅ Brain retrieval animation (node glow sequence) — Task 3
- ✅ Brain write flash — Task 3
- ✅ Opportunity signal board — Task 4
- ✅ Directive flow tracking — Task 2 (`_flow` dict + `/api/flow` endpoint)
- ✅ Board room modal — Task 4
- ✅ Operator reply from dashboard — Task 4
- ✅ Kill switch toggle — Task 4
- ✅ New SSE events: `brain_recall`, `brain_write`, `board_resolution` — Task 2

**Placeholder scan:** No TBD, TODO, or vague instructions found.

**Type consistency:**
- `_parse_directive_target(str) → str | None` — defined Task 2 Step 3, used Task 2 Step 5 ✅
- `_build_flow_matrix(dict[tuple[str,str],int]) → dict` — defined Task 2 Step 3, used in `RedisReader.get_flow()` Task 2 Step 5 ✅
- `RedisReader._flow: dict[tuple[str,str],int]` — initialised Task 2 Step 5, populated in `_handle` ✅
- `SOUNDS.brainWrite()`, `SOUNDS.brainRecall()` etc — defined Task 3 Step 1, called Task 3 Steps 3–4 ✅
- `flashBrainNode(nodeId)`, `glowBrainNodes(nodeIds)` — defined Task 3 Step 4, called in `onEvent` Task 3 Step 3 ✅
- `showBoardModal(text, ts)` — defined Task 4 Step 6, called in `onEvent` Task 3 Step 3 ✅
