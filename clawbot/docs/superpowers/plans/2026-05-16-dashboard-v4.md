# Dashboard V4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 6 observability features to the clawbot dashboard: strategy banner, compounding assets strip, provider health dots, exec directive modal, board resolution log tab, and agent-writable widgets panel.

**Architecture:** Backend extends MetricsStore with DashboardWidget support and adds 6 FastAPI endpoints; scheduler gains `_maybe_widget_update` to parse widget JSON from agent responses; frontend V4 adds info-bar (strategy+assets), provider dots in header, clickable exec cards with full-text modal, board log tab, and a collapsible widgets panel row.

**Tech Stack:** Python 3.12, FastAPI, Redis asyncio, httpx, D3.js, vanilla JS/CSS

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `src/clawbot/metrics.py` | Modify | Add `DashboardWidget` dataclass + `upsert_widget`, `get_widgets`, `remove_widget` |
| `src/clawbot/scheduler.py` | Modify | Add `_maybe_widget_update` module-level async fn; call from both cycle functions |
| `src/clawbot/dashboard/server.py` | Modify | `_build_provider_health`, `ProvidersCache`, extend `RedisReader`, 6 new endpoints |
| `src/clawbot/dashboard/static/index.html` | Modify | Info-bar, provider dots, exec modal, board log tab, widgets panel |
| `agents/{ceo,cfo,cmo,coo,cto}/SOUL.md` | Modify | Document `dashboard_widget` JSON field capability |
| `tests/test_metrics_widgets.py` | Create | Tests for DashboardWidget CRUD methods |
| `tests/test_dashboard_server.py` | Modify | Add `TestBuildProviderHealth` class |
| `tests/test_scheduler_widgets.py` | Create | Tests for `_maybe_widget_update` |

---

### Task 1: DashboardWidget in MetricsStore

**Files:**
- Modify: `src/clawbot/metrics.py`
- Create: `tests/test_metrics_widgets.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_metrics_widgets.py
import pytest
from pathlib import Path
from clawbot.metrics import MetricsStore, DashboardWidget


def _store(tmp_path: Path) -> MetricsStore:
    return MetricsStore(metrics_dir=tmp_path)


def test_get_widgets_empty(tmp_path):
    assert _store(tmp_path).get_widgets() == []


def test_upsert_widget_stores_and_retrieves(tmp_path):
    store = _store(tmp_path)
    w = DashboardWidget(id="ceo_focus", type="text", title="CEO Focus",
                        agent="ceo", content="Grow IR35 revenue")
    store.upsert_widget(w)
    widgets = store.get_widgets()
    assert len(widgets) == 1
    assert widgets[0].id == "ceo_focus"
    assert widgets[0].content == "Grow IR35 revenue"
    assert widgets[0].agent == "ceo"


def test_upsert_widget_overwrites_same_id(tmp_path):
    store = _store(tmp_path)
    store.upsert_widget(DashboardWidget(id="ceo_focus", type="text", title="Old", agent="ceo", content="old"))
    store.upsert_widget(DashboardWidget(id="ceo_focus", type="text", title="New", agent="ceo", content="new"))
    widgets = store.get_widgets()
    assert len(widgets) == 1
    assert widgets[0].content == "new"


def test_remove_widget_deletes_by_id(tmp_path):
    store = _store(tmp_path)
    store.upsert_widget(DashboardWidget(id="w1", type="text", title="T", agent="ceo", content="x"))
    store.upsert_widget(DashboardWidget(id="w2", type="text", title="T", agent="cfo", content="y"))
    store.remove_widget("w1")
    ids = [w.id for w in store.get_widgets()]
    assert ids == ["w2"]


def test_remove_nonexistent_widget_is_noop(tmp_path):
    store = _store(tmp_path)
    store.remove_widget("does_not_exist")  # must not raise


def test_widget_updated_at_is_set(tmp_path):
    store = _store(tmp_path)
    store.upsert_widget(DashboardWidget(id="w", type="text", title="T", agent="ceo", content="c"))
    assert store.get_widgets()[0].updated_at != ""


def test_get_widgets_returns_dataclasses(tmp_path):
    store = _store(tmp_path)
    store.upsert_widget(DashboardWidget(id="w", type="metric", title="Rev",
                        agent="cfo", value=42.0, unit="GBP"))
    w = store.get_widgets()[0]
    assert isinstance(w, DashboardWidget)
    assert w.value == 42.0
    assert w.unit == "GBP"
```

- [ ] **Step 2: Run tests to verify they fail**

```
uv run python -m pytest tests/test_metrics_widgets.py -v --basetemp="C:/tmp/pytest-clawbot"
```

Expected: `ImportError` — `DashboardWidget` not yet defined.

- [ ] **Step 3: Add `DashboardWidget` dataclass and methods to `src/clawbot/metrics.py`**

Add after the `OpportunityFeed` dataclass (after line 75), before the `MetricsStore` class:

```python
@dataclass
class DashboardWidget:
    id: str
    type: str          # "text" | "metric" | "list"
    title: str
    agent: str
    updated_at: str = ""
    content: str = ""
    value: float = 0.0
    unit: str = ""
    max_value: float = 0.0
    items: list[str] = field(default_factory=list)

    def __post_init__(self):
        self.updated_at = self.updated_at or datetime.now(UTC).isoformat()
```

Add these three methods to `MetricsStore` (after `get_top_opportunities`):

```python
    # Dashboard widgets (agent-writable)

    def upsert_widget(self, widget: DashboardWidget) -> None:
        widget.updated_at = datetime.now(UTC).isoformat()
        current = self._read("dashboard_widgets.json", {"widgets": []})
        widgets = current.get("widgets", [])
        widgets = [w for w in widgets if w.get("id") != widget.id]
        widgets.append(asdict(widget))
        self._write("dashboard_widgets.json", {"widgets": widgets})

    def get_widgets(self) -> list[DashboardWidget]:
        current = self._read("dashboard_widgets.json", {"widgets": []})
        return [DashboardWidget(**w) for w in current.get("widgets", [])]

    def remove_widget(self, widget_id: str) -> None:
        current = self._read("dashboard_widgets.json", {"widgets": []})
        widgets = [w for w in current.get("widgets", []) if w.get("id") != widget_id]
        self._write("dashboard_widgets.json", {"widgets": widgets})
```

- [ ] **Step 4: Run tests to verify they pass**

```
uv run python -m pytest tests/test_metrics_widgets.py -v --basetemp="C:/tmp/pytest-clawbot"
```

Expected: 7 tests PASSED.

- [ ] **Step 5: Commit**

```
git add src/clawbot/metrics.py tests/test_metrics_widgets.py
git commit -m "feat: add DashboardWidget dataclass and MetricsStore CRUD methods"
```

---

### Task 2: `_maybe_widget_update` in Scheduler + SOUL.md Updates

**Files:**
- Modify: `src/clawbot/scheduler.py`
- Modify: `agents/ceo/SOUL.md`, `agents/cfo/SOUL.md`, `agents/cmo/SOUL.md`, `agents/coo/SOUL.md`, `agents/cto/SOUL.md`
- Create: `tests/test_scheduler_widgets.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_scheduler_widgets.py
import pytest
from pathlib import Path
from clawbot.scheduler import _maybe_widget_update
from clawbot.metrics import MetricsStore


@pytest.mark.asyncio
async def test_widget_update_from_valid_json(tmp_path):
    response = '''{
      "action": "grow email list",
      "dashboard_widget": {
        "id": "ceo_focus",
        "type": "text",
        "title": "CEO Focus",
        "content": "Grow email list to 500 subscribers"
      }
    }'''
    await _maybe_widget_update(response, "ceo", tmp_path)
    store = MetricsStore(metrics_dir=tmp_path)
    widgets = store.get_widgets()
    assert len(widgets) == 1
    assert widgets[0].id == "ceo_focus"
    assert widgets[0].agent == "ceo"
    assert "email list" in widgets[0].content


@pytest.mark.asyncio
async def test_widget_update_no_widget_field_is_noop(tmp_path):
    response = '{"action": "do something"}'
    await _maybe_widget_update(response, "ceo", tmp_path)
    store = MetricsStore(metrics_dir=tmp_path)
    assert store.get_widgets() == []


@pytest.mark.asyncio
async def test_widget_update_invalid_json_is_noop(tmp_path):
    await _maybe_widget_update("not json at all", "ceo", tmp_path)
    store = MetricsStore(metrics_dir=tmp_path)
    assert store.get_widgets() == []


@pytest.mark.asyncio
async def test_widget_update_missing_id_is_noop(tmp_path):
    response = '{"dashboard_widget": {"type": "text", "title": "T", "content": "c"}}'
    await _maybe_widget_update(response, "ceo", tmp_path)
    store = MetricsStore(metrics_dir=tmp_path)
    assert store.get_widgets() == []


@pytest.mark.asyncio
async def test_widget_update_sets_agent_from_arg(tmp_path):
    response = '{"dashboard_widget": {"id": "cfo_risk", "type": "metric", "title": "Risk", "value": 3.0, "unit": "flags"}}'
    await _maybe_widget_update(response, "cfo", tmp_path)
    widgets = MetricsStore(metrics_dir=tmp_path).get_widgets()
    assert widgets[0].agent == "cfo"


@pytest.mark.asyncio
async def test_widget_update_overwrites_same_id(tmp_path):
    r1 = '{"dashboard_widget": {"id": "ceo_focus", "type": "text", "title": "T", "content": "old"}}'
    r2 = '{"dashboard_widget": {"id": "ceo_focus", "type": "text", "title": "T", "content": "new"}}'
    await _maybe_widget_update(r1, "ceo", tmp_path)
    await _maybe_widget_update(r2, "ceo", tmp_path)
    widgets = MetricsStore(metrics_dir=tmp_path).get_widgets()
    assert len(widgets) == 1
    assert widgets[0].content == "new"
```

- [ ] **Step 2: Run tests to verify they fail**

```
uv run python -m pytest tests/test_scheduler_widgets.py -v --basetemp="C:/tmp/pytest-clawbot"
```

Expected: `ImportError` — `_maybe_widget_update` not yet defined.

- [ ] **Step 3: Add `_maybe_widget_update` to `src/clawbot/scheduler.py`**

Add immediately after `_maybe_escalate` (after line 130), before the `Scheduler` class:

```python
async def _maybe_widget_update(response: str | None, agent_id: str, metrics_dir: Path) -> None:
    """Parse executive JSON response for dashboard_widget field and upsert it."""
    if not response:
        return
    try:
        data = _extract_json(response)
    except Exception:
        return
    raw = data.get("dashboard_widget")
    if not raw or not isinstance(raw, dict):
        return
    widget_id = raw.get("id")
    if not widget_id:
        return
    from clawbot.metrics import MetricsStore, DashboardWidget
    try:
        widget = DashboardWidget(
            id=str(widget_id),
            type=str(raw.get("type", "text")),
            title=str(raw.get("title", "")),
            agent=agent_id,
            content=str(raw.get("content", "")),
            value=float(raw.get("value", 0.0)),
            unit=str(raw.get("unit", "")),
            max_value=float(raw.get("max_value", 0.0)),
            items=list(raw.get("items", [])),
        )
        MetricsStore(metrics_dir=metrics_dir).upsert_widget(widget)
    except Exception as exc:
        logger.warning("_maybe_widget_update failed for %s: %s", agent_id, exc)
```

- [ ] **Step 4: Call `_maybe_widget_update` from both cycle functions**

Find `_run_executive_cycle` and `_run_lieutenant_cycle` (or equivalent) in scheduler.py. After the existing `await _maybe_escalate(self._bus, response, agent_id)` call, add:

```python
        await _maybe_widget_update(response, agent_id, self._metrics_dir)
```

Search for the call site pattern:
```
grep -n "_maybe_escalate" src/clawbot/scheduler.py
```

- [ ] **Step 5: Run tests to verify they pass**

```
uv run python -m pytest tests/test_scheduler_widgets.py -v --basetemp="C:/tmp/pytest-clawbot"
```

Expected: 6 tests PASSED.

- [ ] **Step 6: Update SOUL.md files for all 5 executives**

In each `agents/{ceo,cfo,cmo,coo,cto}/SOUL.md`, add a section in the MUTABLE block documenting the widget capability. Find the `## MUTABLE` section and append before the closing line:

```markdown
### Dashboard Widget Output (Optional)
You may include a `dashboard_widget` field in your JSON response to update the operator dashboard. This is optional — only include it when you have something genuinely useful to surface.

Widget types and fields:
- `type: "text"` — `content` (string, max 200 chars)
- `type: "metric"` — `value` (float), `unit` (string), `max_value` (float, optional)
- `type: "list"` — `items` (array of strings, max 5)

Required fields for all types: `id` (unique snake_case identifier like `ceo_focus`), `type`, `title` (max 40 chars).

Example:
```json
{
  "action": "...",
  "next_wakeup_s": 600,
  "dashboard_widget": {
    "id": "ceo_focus",
    "type": "text",
    "title": "CEO Focus",
    "content": "H1 priority: IR35 tool → £500/mo recurring by July"
  }
}
```
```

- [ ] **Step 7: Commit**

```
git add src/clawbot/scheduler.py tests/test_scheduler_widgets.py agents/
git commit -m "feat: add _maybe_widget_update; enable executives to write dashboard widgets"
```

---

### Task 3: Server Endpoints (Provider Health, Directives, Board Log, Strategy, Assets, Widgets)

**Files:**
- Modify: `src/clawbot/dashboard/server.py`
- Modify: `tests/test_dashboard_server.py`

- [ ] **Step 1: Write failing tests for `_build_provider_health`**

Add `TestBuildProviderHealth` class to `tests/test_dashboard_server.py`:

```python
from clawbot.dashboard.server import _build_provider_health


class TestBuildProviderHealth:
    def test_zero_rpm_is_idle(self):
        result = _build_provider_health("nim-1", 0, 40)
        assert result["name"] == "nim-1"
        assert result["rpm"] == 0
        assert result["max_rpm"] == 40
        assert result["status"] == "idle"

    def test_low_load_is_ok(self):
        result = _build_provider_health("groq", 10, 30)
        assert result["status"] == "ok"

    def test_high_load_is_busy(self):
        result = _build_provider_health("nim-2", 32, 40)
        assert result["status"] == "busy"

    def test_at_limit_is_limit(self):
        result = _build_provider_health("cerebras", 30, 30)
        assert result["status"] == "limit"

    def test_over_limit_is_limit(self):
        result = _build_provider_health("nim-3", 45, 40)
        assert result["status"] == "limit"

    def test_pct_calculation(self):
        result = _build_provider_health("groq", 15, 30)
        assert result["pct"] == 50.0

    def test_zero_max_rpm_does_not_divide_by_zero(self):
        result = _build_provider_health("test", 0, 0)
        assert result["pct"] == 0.0
        assert result["status"] == "idle"
```

- [ ] **Step 2: Run to verify failure**

```
uv run python -m pytest tests/test_dashboard_server.py::TestBuildProviderHealth -v --basetemp="C:/tmp/pytest-clawbot"
```

Expected: `ImportError` — `_build_provider_health` not defined.

- [ ] **Step 3: Add `_build_provider_health` pure function to `server.py`**

Add after `_build_spend_payload` function (search for it — it's near the top of server.py, before the cache classes):

```python
def _build_provider_health(name: str, rpm: int, max_rpm: int) -> dict:
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
```

- [ ] **Step 4: Run to verify passing**

```
uv run python -m pytest tests/test_dashboard_server.py::TestBuildProviderHealth -v --basetemp="C:/tmp/pytest-clawbot"
```

Expected: 7 tests PASSED.

- [ ] **Step 5: Add `ProvidersCache` class to `server.py`**

Add after `RevenueHistoryCache` class:

```python
_PROVIDERS_TTL = 10.0  # seconds


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
```

- [ ] **Step 6: Extend `RedisReader` with `_last_responses` and board log**

In `RedisReader.__init__`, add:

```python
        self._last_responses: dict[str, str] = {}
```

In `RedisReader._handle`, in the branch that handles `.directive` events, after `self._flow` is updated, add:

```python
                # Store full response for exec modal
                agent_id = topic.split(".")[0]  # e.g. "ceo" from "ceo.directive"
                raw = data.get("response_raw", "")
                if raw:
                    self._last_responses[agent_id] = raw
```

Add a `get_last_responses` method:

```python
    def get_last_responses(self) -> dict[str, str]:
        return dict(self._last_responses)
```

For the board log, in the `board.resolution` branch of `_handle`:

```python
                # Append to board_log.jsonl
                import aiofiles
                log_path = Path("/metrics/board_log.jsonl")
                entry = json.dumps({
                    "resolution": data.get("resolution", ""),
                    "ts": data.get("ts", ""),
                    "logged_at": datetime.now(UTC).isoformat(),
                }) + "\n"
                try:
                    async with aiofiles.open(log_path, "a", encoding="utf-8") as f:
                        await f.write(entry)
                except Exception:
                    pass
```

Add `aiofiles` to imports at top of server.py: `import aiofiles`

- [ ] **Step 7: Add 6 new endpoints to `create_app` in `server.py`**

Also add `_providers_cache: ProvidersCache | None = None` to module globals and initialise it in `create_app`:

```python
# In module globals (near _broadcaster etc.)
_providers_cache: ProvidersCache | None = None

# In create_app, after _revenue_history_cache init:
provider_pairs = [(name, _provider_max_rpm(name, settings)) for name in settings.active_provider_names]
_providers_cache = ProvidersCache(redis_url=settings.redis_url, providers=provider_pairs)
```

Add helper (module-level, before `create_app`):

```python
def _provider_max_rpm(name: str, settings) -> int:  # type: ignore[type-arg]
    if name.startswith("nim"):
        return settings.nim_rpm
    if name == "groq":
        return settings.groq_rpm
    if name == "gemini":
        return settings.gemini_rpm
    if name == "cerebras":
        return settings.cerebras_rpm
    return 30
```

Add these 6 endpoints inside `create_app` (alongside existing endpoints):

```python
    @app.get("/api/strategy")
    async def api_strategy():
        path = Path("/metrics/strategy_log.json")
        if not path.exists():
            return {"current_strategy": "undefined", "days_active": 0, "pivot_count_this_month": 0}
        return json.loads(path.read_text(encoding="utf-8"))

    @app.get("/api/assets")
    async def api_assets():
        path = Path("/metrics/compounding_assets.json")
        if not path.exists():
            return {"email_subscribers": 0, "content_pieces_published": 0,
                    "returning_customers": 0, "social_following": 0}
        return json.loads(path.read_text(encoding="utf-8"))

    @app.get("/api/providers")
    async def api_providers():
        if _providers_cache is None:
            return {"providers": []}
        providers = await _providers_cache.get()
        return {"providers": providers}

    @app.get("/api/directives")
    async def api_directives():
        if _reader is None:
            return {"responses": {}}
        return {"responses": _reader.get_last_responses()}

    @app.get("/api/board_log")
    async def api_board_log():
        path = Path("/metrics/board_log.jsonl")
        if not path.exists():
            return {"entries": []}
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        entries = []
        for line in lines[-50:]:  # last 50 resolutions
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        return {"entries": list(reversed(entries))}

    @app.get("/api/widgets")
    async def api_widgets():
        from clawbot.metrics import MetricsStore
        store = MetricsStore()
        return {"widgets": [asdict(w) for w in store.get_widgets()]}
```

Add `from dataclasses import asdict` to server.py imports if not already present.

- [ ] **Step 8: Run full test suite**

```
uv run python -m pytest tests/test_dashboard_server.py -v --basetemp="C:/tmp/pytest-clawbot" --ignore=tests/test_causal_store.py
```

Expected: all existing tests + `TestBuildProviderHealth` PASSED.

- [ ] **Step 9: Commit**

```
git add src/clawbot/dashboard/server.py tests/test_dashboard_server.py
git commit -m "feat: add 6 V4 dashboard endpoints (strategy, assets, providers, directives, board_log, widgets)"
```

---

### Task 4: Frontend V4

**Files:**
- Modify: `src/clawbot/dashboard/static/index.html`

This task is all frontend. No new tests (UI only). All steps show exact HTML/CSS/JS.

- [ ] **Step 1: Add info-bar HTML between `<header>` and `<main>`**

Find the closing `</header>` tag and insert immediately after:

```html
  <!-- V4: strategy + assets info bar -->
  <div id="info-bar">
    <div id="strategy-banner">
      <span class="ib-label">STRATEGY</span>
      <span id="strat-name">loading…</span>
      <span id="strat-meta" class="ib-meta"></span>
    </div>
    <div id="assets-strip">
      <div class="asset-chip"><span class="ac-val" id="a-email">—</span><span class="ac-lbl">subscribers</span></div>
      <div class="asset-chip"><span class="ac-val" id="a-content">—</span><span class="ac-lbl">content pieces</span></div>
      <div class="asset-chip"><span class="ac-val" id="a-customers">—</span><span class="ac-lbl">returning</span></div>
      <div class="asset-chip"><span class="ac-val" id="a-social">—</span><span class="ac-lbl">social</span></div>
    </div>
  </div>
```

- [ ] **Step 2: Add info-bar CSS**

In the `<style>` block, after `.spend-gauge` rules, add:

```css
    #info-bar {
      display: flex; align-items: center; gap: 24px;
      padding: 6px 20px; background: rgba(255,255,255,.03);
      border-bottom: 1px solid rgba(255,255,255,.06); flex-shrink: 0;
    }
    #strategy-banner { display: flex; align-items: center; gap: 8px; flex: 1; min-width: 0; }
    .ib-label { font-size: 9px; font-weight: 700; letter-spacing: .12em;
      color: var(--muted); text-transform: uppercase; }
    #strat-name { font-size: 13px; font-weight: 600; color: var(--cyan);
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .ib-meta { font-size: 11px; color: var(--muted); }
    #assets-strip { display: flex; gap: 16px; flex-shrink: 0; }
    .asset-chip { display: flex; flex-direction: column; align-items: center; }
    .ac-val { font-size: 14px; font-weight: 700; color: var(--green); }
    .ac-lbl { font-size: 9px; color: var(--muted); text-transform: uppercase; letter-spacing: .06em; }
```

- [ ] **Step 3: Add provider health dots to header**

Find the `<header>` element (the one with the title/spend/kill). Inside it, after the existing content, add:

```html
      <div id="provider-dots"></div>
```

Add CSS for provider dots (in `<style>`):

```css
    #provider-dots { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
    .prov-dot { width: 8px; height: 8px; border-radius: 50%; cursor: default;
      transition: transform .2s; }
    .prov-dot:hover { transform: scale(1.6); }
    .prov-dot[data-status="idle"]  { background: var(--muted); }
    .prov-dot[data-status="ok"]    { background: var(--green); }
    .prov-dot[data-status="busy"]  { background: #f59e0b; }
    .prov-dot[data-status="limit"] { background: var(--red); animation: pulse-red 1s infinite; }
    @keyframes pulse-red { 0%,100%{opacity:1} 50%{opacity:.4} }
```

- [ ] **Step 4: Add exec directive modal HTML**

Before `</body>`, add:

```html
  <!-- V4: exec directive modal -->
  <div id="directive-modal" class="modal-overlay" style="display:none">
    <div class="modal-box">
      <div class="modal-header">
        <span id="modal-agent-title">CEO — Last Response</span>
        <button onclick="closeDirectiveModal()" class="modal-close">✕</button>
      </div>
      <pre id="modal-body" class="modal-body"></pre>
    </div>
  </div>
```

Add CSS:

```css
    .modal-overlay { position:fixed; inset:0; background:rgba(0,0,0,.7);
      display:flex; align-items:center; justify-content:center; z-index:1000; }
    .modal-box { background:#0d1321; border:1px solid rgba(255,255,255,.12);
      border-radius:8px; width:min(700px,90vw); max-height:80vh;
      display:flex; flex-direction:column; overflow:hidden; }
    .modal-header { display:flex; justify-content:space-between; align-items:center;
      padding:12px 16px; border-bottom:1px solid rgba(255,255,255,.08); }
    .modal-close { background:none; border:none; color:var(--muted);
      font-size:16px; cursor:pointer; }
    .modal-close:hover { color:var(--text); }
    .modal-body { flex:1; overflow-y:auto; padding:16px; font-size:12px;
      line-height:1.6; white-space:pre-wrap; word-break:break-word;
      color:var(--text); margin:0; }
```

- [ ] **Step 5: Add board log tab to feed-wrap**

Find the `<div id="feed-wrap">` section. Change its header to:

```html
      <div class="feed-tabs">
        <button class="feed-tab active" onclick="switchFeedTab('activity',this)">Activity</button>
        <button class="feed-tab" onclick="switchFeedTab('board',this)">Board</button>
      </div>
      <div id="tab-activity" class="tab-panel">
        <!-- existing #feed content moves here -->
        <ul id="feed"></ul>
      </div>
      <div id="tab-board" class="tab-panel" style="display:none">
        <ul id="board-feed"></ul>
      </div>
```

Add CSS for tabs:

```css
    .feed-tabs { display:flex; gap:0; border-bottom:1px solid rgba(255,255,255,.08); }
    .feed-tab { flex:1; padding:6px 0; background:none; border:none; border-bottom:2px solid transparent;
      color:var(--muted); font-size:11px; cursor:pointer; letter-spacing:.06em; text-transform:uppercase; }
    .feed-tab.active { color:var(--cyan); border-bottom-color:var(--cyan); }
    .tab-panel { flex:1; overflow-y:auto; }
```

- [ ] **Step 6: Add widgets panel HTML row**

Find `<main>` grid. After the existing rows (below flow-row or brain/feed row), add:

```html
  <!-- V4: agent-writable widgets panel -->
  <div id="widgets-row" style="display:none; grid-column:1/-1;">
    <div id="widgets-panel">
      <div class="panel-label">AGENT WIDGETS</div>
      <div id="widgets-grid"></div>
    </div>
  </div>
```

Add CSS:

```css
    #widgets-row { padding: 0 12px 12px; }
    #widgets-panel { background:rgba(255,255,255,.02); border:1px solid rgba(255,255,255,.07);
      border-radius:6px; padding:12px; }
    #widgets-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(200px,1fr)); gap:10px; margin-top:8px; }
    .widget-card { background:#0d1321; border:1px solid rgba(255,255,255,.1); border-radius:6px;
      padding:10px 12px; }
    .wc-title { font-size:10px; text-transform:uppercase; letter-spacing:.08em; color:var(--muted); margin-bottom:4px; }
    .wc-agent { font-size:9px; color:rgba(255,255,255,.25); margin-bottom:6px; }
    .wc-content { font-size:13px; color:var(--text); line-height:1.4; }
    .wc-metric { font-size:22px; font-weight:700; color:var(--cyan); }
    .wc-unit { font-size:11px; color:var(--muted); margin-left:4px; }
    .wc-items { list-style:none; padding:0; margin:0; }
    .wc-items li { font-size:12px; padding:2px 0; color:var(--text); }
    .wc-items li::before { content:"▸ "; color:var(--cyan); }
```

- [ ] **Step 7: Add JS functions**

In the `<script>` section, add all new JS functions:

```javascript
    // ── Strategy + Assets ──────────────────────────────────────────────
    async function loadStrategy() {
      try {
        const d = await fetch('/api/strategy').then(r => r.json());
        document.getElementById('strat-name').textContent = d.current_strategy || 'undefined';
        const meta = [];
        if (d.days_active) meta.push(`day ${d.days_active}`);
        if (d.pivot_count_this_month) meta.push(`${d.pivot_count_this_month} pivots`);
        document.getElementById('strat-meta').textContent = meta.join(' · ');
      } catch(e) {}
    }

    async function loadAssets() {
      try {
        const d = await fetch('/api/assets').then(r => r.json());
        document.getElementById('a-email').textContent = fmtNum(d.email_subscribers);
        document.getElementById('a-content').textContent = fmtNum(d.content_pieces_published);
        document.getElementById('a-customers').textContent = fmtNum(d.returning_customers);
        document.getElementById('a-social').textContent = fmtNum(d.social_following);
      } catch(e) {}
    }

    function fmtNum(n) {
      if (!n) return '0';
      if (n >= 1000) return (n/1000).toFixed(1)+'k';
      return String(n);
    }

    // ── Provider health dots ────────────────────────────────────────────
    async function loadProviders() {
      try {
        const d = await fetch('/api/providers').then(r => r.json());
        const el = document.getElementById('provider-dots');
        el.innerHTML = '';
        for (const p of (d.providers || [])) {
          const dot = document.createElement('div');
          dot.className = 'prov-dot';
          dot.dataset.status = p.status;
          dot.title = `${p.name}: ${p.rpm}/${p.max_rpm} RPM (${p.status})`;
          el.appendChild(dot);
        }
      } catch(e) {}
    }

    // ── Exec directive modal ────────────────────────────────────────────
    let _lastResponses = {};

    async function loadDirectives() {
      try {
        const d = await fetch('/api/directives').then(r => r.json());
        _lastResponses = d.responses || {};
      } catch(e) {}
    }

    function openDirectiveModal(agentId) {
      const raw = _lastResponses[agentId];
      if (!raw) return;
      document.getElementById('modal-agent-title').textContent =
        agentId.toUpperCase() + ' — Last Response';
      try {
        document.getElementById('modal-body').textContent =
          JSON.stringify(JSON.parse(raw), null, 2);
      } catch(e) {
        document.getElementById('modal-body').textContent = raw;
      }
      document.getElementById('directive-modal').style.display = 'flex';
    }

    function closeDirectiveModal() {
      document.getElementById('directive-modal').style.display = 'none';
    }

    document.getElementById('directive-modal').addEventListener('click', e => {
      if (e.target === e.currentTarget) closeDirectiveModal();
    });

    // ── Board log tab ───────────────────────────────────────────────────
    function switchFeedTab(tab, btn) {
      document.querySelectorAll('.feed-tab').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById('tab-activity').style.display = tab === 'activity' ? '' : 'none';
      document.getElementById('tab-board').style.display = tab === 'board' ? '' : 'none';
      if (tab === 'board') loadBoardLog();
    }

    async function loadBoardLog() {
      try {
        const d = await fetch('/api/board_log').then(r => r.json());
        const ul = document.getElementById('board-feed');
        ul.innerHTML = '';
        for (const e of (d.entries || [])) {
          const li = document.createElement('li');
          const ts = e.logged_at ? new Date(e.logged_at).toLocaleTimeString() : '';
          li.innerHTML = `<span class="ts">${ts}</span> ${escHtml(e.resolution || '')}`;
          ul.appendChild(li);
        }
        if (!d.entries?.length) {
          ul.innerHTML = '<li style="color:var(--muted);font-size:11px">No resolutions yet</li>';
        }
      } catch(e) {}
    }

    function escHtml(s) {
      return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    }

    // ── Agent widgets panel ─────────────────────────────────────────────
    async function loadWidgets() {
      try {
        const d = await fetch('/api/widgets').then(r => r.json());
        const widgets = d.widgets || [];
        const row = document.getElementById('widgets-row');
        const grid = document.getElementById('widgets-grid');
        if (!widgets.length) { row.style.display = 'none'; return; }
        row.style.display = '';
        grid.innerHTML = '';
        for (const w of widgets) {
          const card = document.createElement('div');
          card.className = 'widget-card';
          let body = '';
          if (w.type === 'metric') {
            body = `<div class="wc-metric">${w.value}<span class="wc-unit">${escHtml(w.unit)}</span></div>`;
          } else if (w.type === 'list') {
            const items = (w.items || []).map(i => `<li>${escHtml(i)}</li>`).join('');
            body = `<ul class="wc-items">${items}</ul>`;
          } else {
            body = `<div class="wc-content">${escHtml(w.content)}</div>`;
          }
          card.innerHTML = `
            <div class="wc-title">${escHtml(w.title)}</div>
            <div class="wc-agent">${escHtml(w.agent)}</div>
            ${body}`;
          grid.appendChild(card);
        }
      } catch(e) {}
    }
```

- [ ] **Step 8: Wire exec card click handlers**

Find the existing exec card rendering JS (where `.exec-card` elements are built). Add `onclick` handler:

```javascript
    // In the card rendering loop, add to each card:
    card.style.cursor = 'pointer';
    card.addEventListener('click', () => openDirectiveModal(agent.id));
```

If exec cards are rendered as static HTML in the body (not dynamically), add `onclick="openDirectiveModal('ceo')"` etc. to each card `<div>`.

- [ ] **Step 9: Update boot sequence to call new loaders**

In the `window.addEventListener('DOMContentLoaded', ...)` or equivalent boot function, add:

```javascript
    loadStrategy();
    loadAssets();
    loadProviders();
    loadDirectives();
    loadWidgets();
    setInterval(loadStrategy, 60_000);
    setInterval(loadAssets, 60_000);
    setInterval(loadProviders, 15_000);
    setInterval(loadDirectives, 30_000);
    setInterval(loadWidgets, 30_000);
```

- [ ] **Step 10: Commit**

```
git add src/clawbot/dashboard/static/index.html
git commit -m "feat: dashboard V4 frontend — info-bar, provider dots, exec modal, board tab, widgets panel"
```

---

### Task 5: Deploy

- [ ] **Step 1: Run full test suite locally**

```
uv run python -m pytest tests/ -v --basetemp="C:/tmp/pytest-clawbot" --ignore=tests/test_causal_store.py
```

Expected: all tests PASSED, no failures.

- [ ] **Step 2: Deploy updated files to VPS**

```bash
scp src/clawbot/metrics.py clawbot:/opt/clawbot/src/clawbot/metrics.py
scp src/clawbot/scheduler.py clawbot:/opt/clawbot/src/clawbot/scheduler.py
scp src/clawbot/dashboard/server.py clawbot:/opt/clawbot/src/clawbot/dashboard/server.py
scp src/clawbot/dashboard/static/index.html clawbot:/opt/clawbot/src/clawbot/dashboard/static/index.html
scp -r agents/ clawbot:/opt/clawbot/agents/
```

- [ ] **Step 3: Install aiofiles on VPS (if not already present)**

```bash
ssh clawbot 'cd /opt/clawbot && pip install aiofiles'
```

Check first: `ssh clawbot 'pip show aiofiles'`

- [ ] **Step 4: Restart container**

```bash
ssh clawbot 'cd /opt/clawbot && docker compose restart clawbot'
```

- [ ] **Step 5: Smoke-test all new endpoints**

```bash
curl -s http://178.105.128.174:8080/api/strategy | python3 -m json.tool
curl -s http://178.105.128.174:8080/api/assets | python3 -m json.tool
curl -s http://178.105.128.174:8080/api/providers | python3 -m json.tool
curl -s http://178.105.128.174:8080/api/directives | python3 -m json.tool
curl -s http://178.105.128.174:8080/api/board_log | python3 -m json.tool
curl -s http://178.105.128.174:8080/api/widgets | python3 -m json.tool
```

Expected: all return valid JSON, no 404 or 500.

- [ ] **Step 6: Commit**

```
git add .
git commit -m "chore: deploy dashboard V4 to production"
```

---

## Self-Review

**Spec coverage:**
- [x] Strategy banner — `/api/strategy`, info-bar HTML, `loadStrategy()`
- [x] Compounding assets strip — `/api/assets`, asset chips, `loadAssets()`
- [x] Provider health dots — `_build_provider_health`, `ProvidersCache`, `/api/providers`, dot rendering
- [x] Exec directive modal — `_last_responses` in RedisReader, `/api/directives`, modal HTML/JS
- [x] Board resolution log — append in `_handle`, `/api/board_log`, board tab UI
- [x] Agent-writable widgets panel — `DashboardWidget` + MetricsStore CRUD, `_maybe_widget_update`, `/api/widgets`, widgets grid UI, SOUL.md updates

**Placeholder scan:** No TBDs, no "similar to Task N" references, all code blocks complete.

**Type consistency:** `DashboardWidget` defined in Task 1, imported via `from clawbot.metrics import MetricsStore, DashboardWidget` in Task 2. `_build_provider_health` defined in Task 3 step 3, tested in step 1-2. `_last_responses` added in Task 3 step 6, referenced by `/api/directives` in step 7.
