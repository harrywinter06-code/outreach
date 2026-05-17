# Dashboard V3 — Spend Gauge, Flow Diagram, Revenue Sparkline, Comms Overlay

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add four operational metrics to the dashboard: a daily spend arc gauge in the header, a directive flow arc diagram between exec cards, a 14-day revenue sparkline below the revenue figure, and an animated particle overlay showing live agent-to-agent message sends.

**Architecture:** One new GumroadClient method (`sales_by_day_gbp`) feeds a cached `RevenueHistoryCache` in the dashboard server; a `SpendCache` reads the existing `clawbot:spend:{date}` Redis hash; two new GET endpoints (`/api/spend`, `/api/revenue_history`) feed the frontend. The flow diagram and comms overlay are pure frontend using existing `/api/flow` and SSE `cycle_complete` events respectively.

**Tech Stack:** asyncpg/asyncio (existing), redis.asyncio (existing), GumroadClient (existing), D3 v7 (existing CDN), Web Audio API (existing), HTML Canvas 2D API

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Modify | `src/clawbot/gumroad.py` | Add `_group_sales_by_day` pure helper + `sales_by_day_gbp` method |
| Modify | `src/clawbot/dashboard/server.py` | `_build_spend_payload`, `SpendCache`, `RevenueHistoryCache`, two new GET endpoints |
| Modify | `src/clawbot/dashboard/static/index.html` | Spend gauge, revenue sparkline, flow arc diagram, comms particle overlay |
| Modify | `tests/test_gumroad.py` | Tests for `_group_sales_by_day` |
| Modify | `tests/test_dashboard_server.py` | Tests for `_build_spend_payload` |

---

## Task 1: `sales_by_day_gbp` on GumroadClient

**Files:**
- Modify: `src/clawbot/gumroad.py`
- Test: `tests/test_gumroad.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_gumroad.py`:

```python
from datetime import timedelta
from clawbot.gumroad import _group_sales_by_day, GumroadSale


def _sale(price: float, days_ago: float = 0) -> GumroadSale:
    return GumroadSale("s1", "p1", price, datetime.now(UTC) - timedelta(days=days_ago))


class TestGroupSalesByDay:
    def test_empty_fills_zeros(self):
        result = _group_sales_by_day([], days=7)
        assert len(result) == 7
        assert all(v == 0.0 for v in result.values())

    def test_sums_same_day_sales(self):
        sales = [_sale(9.99), _sale(4.99)]
        result = _group_sales_by_day(sales, days=7)
        today = datetime.now(UTC).date().isoformat()
        assert abs(result[today] - 14.98) < 0.01

    def test_groups_different_days(self):
        sales = [_sale(9.99, days_ago=0), _sale(4.99, days_ago=1)]
        result = _group_sales_by_day(sales, days=7)
        today = datetime.now(UTC).date().isoformat()
        yesterday = (datetime.now(UTC) - timedelta(days=1)).date().isoformat()
        assert abs(result[today] - 9.99) < 0.01
        assert abs(result[yesterday] - 4.99) < 0.01

    def test_excludes_out_of_range_sales(self):
        sales = [_sale(99.0, days_ago=30)]
        result = _group_sales_by_day(sales, days=7)
        assert all(v == 0.0 for v in result.values())

    def test_returns_14_days_when_requested(self):
        result = _group_sales_by_day([], days=14)
        assert len(result) == 14
```

- [ ] **Step 2: Run tests to confirm they fail**

```
uv run python -m pytest tests/test_gumroad.py::TestGroupSalesByDay -x -q --basetemp="C:/tmp/pytest-clawbot"
```

Expected: `ImportError: cannot import name '_group_sales_by_day'`

- [ ] **Step 3: Add `_group_sales_by_day` and `sales_by_day_gbp` to `gumroad.py`**

In `src/clawbot/gumroad.py`, after the `_pence_to_gbp` function at the bottom:

```python
def _group_sales_by_day(sales: list[GumroadSale], days: int = 14) -> dict[str, float]:
    """Group sales amounts by UTC date for the last `days` days.

    Dates with no sales are included with 0.0 so callers get a complete sequence.
    """
    from datetime import date, timedelta as td
    today = datetime.now(UTC).date()
    result: dict[str, float] = {
        (today - td(days=i)).isoformat(): 0.0
        for i in range(days - 1, -1, -1)
    }
    for sale in sales:
        day = sale.created_at.date().isoformat()
        if day in result:
            result[day] = result[day] + sale.price_gbp
    return result
```

In the `GumroadClient` class, after `sales_last_7_days_gbp`:

```python
    async def sales_by_day_gbp(self, days: int = 14) -> dict[str, float]:
        """GBP sales grouped by UTC date for the last `days` days."""
        after = datetime.now(UTC) - timedelta(days=days)
        sales = await self.sales(after=after)
        return _group_sales_by_day(sales, days)
```

- [ ] **Step 4: Run tests to confirm they pass**

```
uv run python -m pytest tests/test_gumroad.py::TestGroupSalesByDay -x -q --basetemp="C:/tmp/pytest-clawbot"
```

Expected: 5 passed.

- [ ] **Step 5: Run full suite to confirm no regressions**

```
uv run python -m pytest -x -q --basetemp="C:/tmp/pytest-clawbot"
```

Expected: 277 passed.

- [ ] **Step 6: Commit**

```bash
git add src/clawbot/gumroad.py tests/test_gumroad.py
git commit -m "feat: add sales_by_day_gbp and _group_sales_by_day to GumroadClient"
```

---

## Task 2: New server.py helpers and endpoints

**Files:**
- Modify: `src/clawbot/dashboard/server.py`
- Test: `tests/test_dashboard_server.py`

Add:
1. `_build_spend_payload(spent_usd, max_usd)` — pure function, testable
2. `SpendCache` — reads Redis `clawbot:spend:{date}` hash, cached 5s
3. `RevenueHistoryCache` — calls `GumroadClient.sales_by_day_gbp`, cached 10 min
4. `/api/spend` and `/api/revenue_history` endpoints

- [ ] **Step 1: Write failing tests**

Add to `tests/test_dashboard_server.py`:

```python
from clawbot.dashboard.server import _build_spend_payload


class TestBuildSpendPayload:
    def test_zero_spend(self):
        assert _build_spend_payload(0.0, 5.0) == {"spent_usd": 0.0, "max_usd": 5.0, "pct": 0.0}

    def test_half_spent(self):
        result = _build_spend_payload(2.5, 5.0)
        assert result["pct"] == 50.0

    def test_over_limit_allowed(self):
        result = _build_spend_payload(6.0, 5.0)
        assert result["pct"] == 120.0

    def test_zero_max_does_not_divide_by_zero(self):
        result = _build_spend_payload(1.0, 0.0)
        assert result["pct"] == 0.0
```

- [ ] **Step 2: Run tests to confirm they fail**

```
uv run python -m pytest tests/test_dashboard_server.py::TestBuildSpendPayload -x -q --basetemp="C:/tmp/pytest-clawbot"
```

Expected: `ImportError: cannot import name '_build_spend_payload'`

- [ ] **Step 3: Add `_build_spend_payload` to `server.py`**

In `src/clawbot/dashboard/server.py`, after `_build_flow_matrix` and before the `# ── Redis stream reader` block:

```python
def _build_spend_payload(spent_usd: float, max_usd: float) -> dict[str, Any]:
    pct = round(spent_usd / max_usd * 100, 1) if max_usd > 0 else 0.0
    return {"spent_usd": round(spent_usd, 4), "max_usd": max_usd, "pct": pct}
```

- [ ] **Step 4: Run tests to confirm they pass**

```
uv run python -m pytest tests/test_dashboard_server.py::TestBuildSpendPayload -x -q --basetemp="C:/tmp/pytest-clawbot"
```

Expected: 4 passed.

- [ ] **Step 5: Add `SpendCache` and `RevenueHistoryCache` to `server.py`**

Add these two classes after `_build_spend_payload`, still before `# ── Redis stream reader`:

```python
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
```

- [ ] **Step 6: Wire `SpendCache` and `RevenueHistoryCache` into `create_app`**

Near the top of the module (with the other module-level globals, around line 251):

```python
_broadcaster: EventBroadcaster | None = None
_brain_cache: BrainCache | None = None
_reader: "RedisReader | None" = None
_spend_cache: SpendCache | None = None
_revenue_history_cache: RevenueHistoryCache | None = None
```

At the top of `create_app`, extend the `global` declaration and initialise:

```python
def create_app(db_pool: Any, redis_url: str) -> Any:
    global _broadcaster, _brain_cache, _spend_cache, _revenue_history_cache
    from clawbot.config import settings
    _broadcaster = EventBroadcaster()
    _brain_cache = BrainCache(db_pool)
    _spend_cache = SpendCache(redis_url=redis_url, max_usd=settings.max_daily_spend_usd)
    _revenue_history_cache = RevenueHistoryCache(gumroad_api_key=settings.gumroad_api_key)
```

- [ ] **Step 7: Add `/api/spend` and `/api/revenue_history` endpoints**

Inside `create_app`, after the existing `/api/flow` route and before `/api/reply`:

```python
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
```

- [ ] **Step 8: Run full test suite**

```
uv run python -m pytest -x -q --basetemp="C:/tmp/pytest-clawbot"
```

Expected: 281 passed (272 + 4 new + 5 from Task 1).

- [ ] **Step 9: Commit**

```bash
git add src/clawbot/dashboard/server.py tests/test_dashboard_server.py
git commit -m "feat: /api/spend and /api/revenue_history endpoints with SpendCache + RevenueHistoryCache"
```

---

## Task 3: Frontend — spend gauge + revenue sparkline

**Files:**
- Modify: `src/clawbot/dashboard/static/index.html`

No backend changes. All data comes from `/api/spend` and `/api/revenue_history`.

- [ ] **Step 1: Add CSS for spend gauge and revenue sparkline**

In the `<style>` block, after the `.kill-clock` / `.kill-fill` rules and before the `/* ── MAIN GRID */` comment:

```css
/* ── SPEND GAUGE ────────────────────────────────────────────────── */
.spend-gauge{
  display:flex;flex-direction:column;align-items:flex-end;gap:4px;
  padding-left:14px;border-left:1px solid var(--border);
}
.spend-label{font-size:9px;color:var(--muted);font-weight:600;letter-spacing:.08em;text-transform:uppercase}
.spend-row{display:flex;align-items:center;gap:6px}
.spend-val{font-size:11px;font-weight:700;color:var(--text);font-variant-numeric:tabular-nums;min-width:44px;text-align:right}
.spend-track{width:60px;height:3px;background:var(--muted2);border-radius:2px;overflow:hidden}
.spend-fill{height:100%;border-radius:2px;background:var(--green);transition:width .6s,background .6s}
.spend-max{font-size:9px;color:var(--muted);font-variant-numeric:tabular-nums}

/* ── REVENUE SPARKLINE ───────────────────────────────────────────── */
.rev-spark{display:flex;gap:2px;align-items:flex-end;height:18px;margin-top:3px}
.rev-bar{width:5px;border-radius:1px 1px 0 0;transition:height .4s,background .4s;min-height:2px;cursor:default}
```

- [ ] **Step 2: Add spend gauge HTML to header**

In `<header>`, between `.kill-clock` and the `#snd-btn` button:

```html
  <div class="spend-gauge">
    <div class="spend-label">Today's spend</div>
    <div class="spend-row">
      <div class="spend-val" id="spend-val">$0.00</div>
      <div class="spend-track"><div class="spend-fill" id="spend-fill" style="width:0%"></div></div>
      <div class="spend-max" id="spend-max">/$5.00</div>
    </div>
  </div>
```

- [ ] **Step 3: Add sparkline container inside `.revenue`**

Replace the existing `.revenue` HTML block:

```html
  <div class="revenue">
    <div class="revenue-label">7-day revenue</div>
    <div class="revenue-value" id="rev">£0.00</div>
    <div class="rev-spark" id="rev-spark"></div>
  </div>
```

- [ ] **Step 4: Add `updateSpend` and `renderSparkline` JS functions**

Add these two functions after `setRev` (around line 290 in the script):

```javascript
function updateSpend(d) {
  if (!d) return;
  const val = document.getElementById('spend-val');
  const fill = document.getElementById('spend-fill');
  const max  = document.getElementById('spend-max');
  if (val)  val.textContent  = '$' + parseFloat(d.spent_usd || 0).toFixed(2);
  if (max)  max.textContent  = '/$' + parseFloat(d.max_usd || 5).toFixed(2);
  const pct = Math.min(100, parseFloat(d.pct || 0));
  if (fill) {
    fill.style.width = pct + '%';
    fill.style.background = pct < 60 ? 'var(--green)' : pct < 85 ? 'var(--amber)' : 'var(--red)';
  }
}

function renderSparkline(history) {
  const wrap = document.getElementById('rev-spark');
  if (!wrap || !history || !history.length) return;
  const max = Math.max(...history.map(d => d.amount), 0.01);
  const todayStr = new Date().toISOString().slice(0, 10);
  wrap.innerHTML = history.map(d => {
    const h = Math.max(2, Math.round((d.amount / max) * 16));
    const isToday = d.date === todayStr;
    const bg = isToday ? 'var(--cyan)' : d.amount > 0 ? 'rgba(16,185,129,.7)' : 'var(--muted2)';
    return `<div class="rev-bar" style="height:${h}px;background:${bg}" title="${d.date}: £${d.amount.toFixed(2)}"></div>`;
  }).join('');
}
```

- [ ] **Step 5: Fetch spend + sparkline data on boot**

In the boot section, after the `loadBrain` / `setInterval(loadBrain, 30000)` lines, add:

```javascript
function loadSpend() {
  fetch('/api/spend').then(r => r.json()).then(updateSpend).catch(() => {});
}
loadSpend();
setInterval(loadSpend, 10000);

function loadSparkline() {
  fetch('/api/revenue_history').then(r => r.json()).then(renderSparkline).catch(() => {});
}
loadSparkline();
setInterval(loadSparkline, 300000);  // re-fetch every 5 min (Gumroad data)
```

- [ ] **Step 6: Hot-patch frontend and verify**

```bash
scp src/clawbot/dashboard/server.py clawbot:/opt/clawbot/src/clawbot/dashboard/server.py
scp src/clawbot/dashboard/static/index.html clawbot:/opt/clawbot/src/clawbot/dashboard/static/index.html
ssh clawbot 'cd /opt/clawbot && docker compose restart clawbot'
```

Wait 15 seconds, then:

```bash
curl -s http://178.105.128.174:8080/api/spend
curl -s http://178.105.128.174:8080/api/revenue_history | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d), 'days,', d[-1])"
```

Expected: `/api/spend` returns `{"spent_usd": X, "max_usd": 5.0, "pct": Y}`. `/api/revenue_history` returns 14 entries. Open browser and confirm spend gauge appears in header with a colored bar, and sparkline bars appear below `£XX.XX`.

- [ ] **Step 7: Commit**

```bash
git add src/clawbot/dashboard/static/index.html
git commit -m "feat: spend gauge and revenue sparkline in dashboard header"
```

---

## Task 4: Frontend — directive flow arc diagram + agent comms overlay

**Files:**
- Modify: `src/clawbot/dashboard/static/index.html`

No backend changes. Flow diagram uses existing `/api/flow` endpoint. Comms overlay uses existing SSE `cycle_complete` events (which already carry a `to` field).

- [ ] **Step 1: Add CSS for flow row and comms canvas**

In the `<style>` block, after the `/* ── BRAIN */` section rules:

```css
/* ── FLOW ROW ────────────────────────────────────────────────────── */
#flow-row{
  grid-column:1/-1;
  background:var(--bg);border-bottom:1px solid var(--border);
  max-height:0;overflow:hidden;
  transition:max-height .4s ease;
}
#flow-row.visible{max-height:72px}
#flow-svg{display:block}

/* ── COMMS OVERLAY ───────────────────────────────────────────────── */
.exec-strip{position:relative}
#flow-canvas{
  position:absolute;inset:0;pointer-events:none;z-index:10;
}
```

- [ ] **Step 2: Update main grid to 3 rows**

Find the `main` CSS rule and change `grid-template-rows`:

```css
main{
  flex:1;overflow:hidden;
  display:grid;
  grid-template-rows:148px auto 1fr;
  grid-template-columns:1fr 360px;
  gap:1px;
  background:var(--border);
}
```

- [ ] **Step 3: Add `#flow-row` and `#flow-canvas` HTML**

Inside `<main>`, after the exec strip `<div>` and before `#brain-wrap`, add:

```html
  <div id="flow-row">
    <svg id="flow-svg" width="100%" height="70"></svg>
  </div>
```

Inside the exec strip `<div class="exec-strip" id="strip">`, add the canvas as the first child:

```html
  <div class="exec-strip" id="strip">
    <canvas id="flow-canvas"></canvas>
  </div>
```

- [ ] **Step 4: Add `renderFlowDiagram` JS function**

Add after the `renderLegend()` call in the script:

```javascript
// ── Directive flow arc diagram ────────────────────────────────────
function renderFlowDiagram(data) {
  const row = document.getElementById('flow-row');
  const svg = document.getElementById('flow-svg');
  if (!row || !svg) return;
  const edges = (data && data.edges) || [];
  if (!edges.length) { row.classList.remove('visible'); return; }
  row.classList.add('visible');

  const W = svg.clientWidth || svg.parentElement.clientWidth || 800;
  const H = 70;
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);

  const agents = ['ceo','cfo','cmo','coo','cto'];
  const cx = i => Math.round((i + 0.5) * W / agents.length);
  const nodeY = 54;

  let html = '';

  for (const e of edges) {
    const i = agents.indexOf(e.from), j = agents.indexOf(e.to);
    if (i < 0 || j < 0) continue;
    const x1 = cx(i), x2 = cx(j);
    const midX = (x1 + x2) / 2;
    const arcH  = 22 + Math.abs(x1 - x2) * 0.06;
    const ctrlY = nodeY - arcH;
    const w = Math.max(1, Math.log2(e.count + 1) * 1.4).toFixed(1);
    html += `<path d="M${x1},${nodeY} Q${midX},${ctrlY} ${x2},${nodeY}" stroke="rgba(0,212,255,0.35)" stroke-width="${w}" fill="none"/>`;
    html += `<text x="${midX}" y="${ctrlY - 4}" text-anchor="middle" font-size="9" fill="rgba(100,116,139,.85)">${e.count}</text>`;
  }

  for (let i = 0; i < agents.length; i++) {
    html += `<circle cx="${cx(i)}" cy="${nodeY}" r="9" fill="var(--bg)" stroke="var(--border)" stroke-width="1"/>`;
    html += `<text x="${cx(i)}" y="${nodeY + 4}" text-anchor="middle" font-size="8" fill="var(--muted)" font-weight="800" letter-spacing=".08em">${agents[i].toUpperCase()}</text>`;
  }

  svg.innerHTML = html;
}

function loadFlow() {
  fetch('/api/flow').then(r => r.json()).then(renderFlowDiagram).catch(() => {});
}
loadFlow();
setInterval(loadFlow, 30000);
```

- [ ] **Step 5: Add comms particle overlay JS**

Add after `renderFlowDiagram` / `loadFlow`:

```javascript
// ── Agent comms particle overlay ──────────────────────────────────
const _particles = [];
let _rafRunning = false;

function animateFlow(fromAgent, toAgent) {
  const fromCard = document.getElementById('card-' + fromAgent);
  const toCard   = document.getElementById('card-' + toAgent);
  const canvas   = document.getElementById('flow-canvas');
  if (!fromCard || !toCard || !canvas) return;

  const cr = canvas.getBoundingClientRect();
  const fr = fromCard.getBoundingClientRect();
  const tr = toCard.getBoundingClientRect();

  canvas.width  = canvas.offsetWidth;
  canvas.height = canvas.offsetHeight;

  _particles.push({
    x1: fr.left + fr.width / 2 - cr.left,
    y1: fr.bottom - 8 - cr.top,
    x2: tr.left + tr.width / 2 - cr.left,
    y2: tr.bottom - 8 - cr.top,
    start: performance.now(),
    duration: 1100,
  });
  if (!_rafRunning) { _rafRunning = true; requestAnimationFrame(_drawParticles); }
}

function _drawParticles(now) {
  const canvas = document.getElementById('flow-canvas');
  if (!canvas) { _rafRunning = false; return; }
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  for (let i = _particles.length - 1; i >= 0; i--) {
    const p = _particles[i];
    const t = Math.min(1, (now - p.start) / p.duration);
    const mx = (p.x1 + p.x2) / 2;
    const my = Math.min(p.y1, p.y2) - 32;
    const x = (1-t)*(1-t)*p.x1 + 2*(1-t)*t*mx + t*t*p.x2;
    const y = (1-t)*(1-t)*p.y1 + 2*(1-t)*t*my + t*t*p.y2;
    const alpha = t < 0.75 ? 1 : (1 - t) / 0.25;
    ctx.beginPath();
    ctx.arc(x, y, 4, 0, Math.PI * 2);
    ctx.fillStyle = `rgba(0,212,255,${alpha.toFixed(2)})`;
    ctx.shadowColor = '#00d4ff';
    ctx.shadowBlur = 10;
    ctx.fill();
    if (t >= 1) _particles.splice(i, 1);
  }

  if (_particles.length > 0) {
    requestAnimationFrame(_drawParticles);
  } else {
    _rafRunning = false;
  }
}
```

- [ ] **Step 6: Call `animateFlow` from `onEvent`**

In `onEvent`, inside the `cycle_complete` block, add after `SOUNDS.cycleComplete()`:

```javascript
  if (ev.type === 'cycle_complete') {
    const s = S[ev.agent]; if (!s) return;
    s.status = ev.success ? 'success' : 'error';
    s.t0 = 0;
    if (ev.action) s.action = ev.action;
    s.cycles = [...s.cycles.slice(-9), !!ev.success];
    renderCard(ev.agent);
    pushFeed(ev);
    SOUNDS.cycleComplete();
    if (ev.to && ev.to !== ev.agent) animateFlow(ev.agent, ev.to);
    setTimeout(() => { s.status = 'idle'; renderCard(ev.agent); }, 3500);
  }
```

- [ ] **Step 7: Hot-patch and verify**

```bash
scp src/clawbot/dashboard/static/index.html clawbot:/opt/clawbot/src/clawbot/dashboard/static/index.html
```

Open `http://178.105.128.174:8080`. Verify:
- Header shows spend gauge bar (green while low)
- Header shows 14 tiny sparkline bars below £XX.XX
- Wait for a `cycle_complete` event with a `to` field — a cyan particle should travel from the source exec card to the target

To force-test the flow diagram without waiting for real data:

```bash
curl -s http://178.105.128.174:8080/api/flow
```

If edges exist (after some directive cycles), the arc diagram row should appear below the exec strip.

- [ ] **Step 8: Run full test suite**

```
uv run python -m pytest -x -q --basetemp="C:/tmp/pytest-clawbot"
```

Expected: 281 passed.

- [ ] **Step 9: Commit**

```bash
git add src/clawbot/dashboard/static/index.html
git commit -m "feat: directive flow arc diagram and agent comms particle overlay"
```

---

## Self-Review

**Spec coverage:**
- ✅ Spend gauge — Tasks 2 + 3 (`SpendCache`, `/api/spend`, header widget with colored bar)
- ✅ Directive flow Sankey/arc diagram — Task 4 (`renderFlowDiagram`, SVG arcs in `#flow-row`)
- ✅ Revenue sparkline — Tasks 1 + 2 + 3 (`sales_by_day_gbp`, `RevenueHistoryCache`, `/api/revenue_history`, sparkline bars)
- ✅ Agent comms overlay — Task 4 (`animateFlow`, canvas particles triggered by `cycle_complete.to`)

**Placeholder scan:** No TBDs or vague instructions found.

**Type consistency:**
- `_build_spend_payload(float, float) → dict` — defined Task 2 Step 3, used in `SpendCache.get()` Task 2 Step 5 ✅
- `SpendCache.get() → dict[str, Any]` — defined Task 2 Step 5, called in `/api/spend` Task 2 Step 7 ✅
- `RevenueHistoryCache.get() → list[dict[str, Any]]` — defined Task 2 Step 5, called in `/api/revenue_history` Task 2 Step 7 ✅
- `_group_sales_by_day(list[GumroadSale], int) → dict[str, float]` — defined Task 1 Step 3, used in `sales_by_day_gbp` Task 1 Step 3 ✅
- `renderSparkline(history: Array<{date, amount}>)` — defined Task 3 Step 4, called Task 3 Step 5 ✅
- `updateSpend(d: {spent_usd, max_usd, pct})` — defined Task 3 Step 4, called Task 3 Step 5 ✅
- `renderFlowDiagram(data: {edges, total})` — defined Task 4 Step 4, called Task 4 Step 4 (loadFlow) ✅
- `animateFlow(fromAgent, toAgent)` — defined Task 4 Step 5, called Task 4 Step 6 (onEvent) ✅
- `_drawParticles(now: DOMHighResTimeStamp)` — defined Task 4 Step 5, called via `requestAnimationFrame` Task 4 Step 5 ✅
