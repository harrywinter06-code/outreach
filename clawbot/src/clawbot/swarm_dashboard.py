"""
Z-OBS — /swarm dashboard page. The first thing the operator hits in the
morning to see what the autonomous substrate actually produced overnight.

Shows in one page:
- Per-business state (fitness, revenue, stall, last cycle)
- Recent lander visits (URL access via FastAPI request log if available;
  otherwise we count via business_leads + business_revenue inserts)
- Captured leads (last 20)
- Real revenue (non-self-paid, last 20)
- Recent publishing artifacts (skill_calls with ok=true on artifact actions)
- Per-credential health (which vault secrets exist for which platform)

Pure read-only HTML — no JS framework. Refreshes every 30s via meta-refresh.
Designed to be readable on phone (mobile-first single-column).
"""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

logger = logging.getLogger(__name__)

DB_POOL: Any | None = None
ACCOUNTS_STORE: Any | None = None


def get_router() -> APIRouter:
    router = APIRouter()

    @router.get("/swarm", response_class=HTMLResponse)
    async def swarm_page(request: Request):
        if DB_POOL is None:
            return HTMLResponse("<h1>DB not wired</h1>", status_code=500)
        try:
            data = await _gather_state()
            html = _render(data)
            return HTMLResponse(html)
        except Exception as exc:
            logger.error("swarm dashboard render failed: %s", exc, exc_info=True)
            return HTMLResponse(f"<h1>error</h1><pre>{_esc(repr(exc))}</pre>", status_code=500)

    return router


async def _gather_state() -> dict:
    out: dict = {}
    async with DB_POOL.acquire() as conn:
        # Active businesses
        out["businesses"] = [dict(r) for r in await conn.fetch(
            "SELECT business_id, name, niche, status, fitness_score, "
            "revenue_total_gbp, metadata, "
            "EXTRACT(EPOCH FROM (NOW() - spawned_at))/3600 AS age_h, "
            "EXTRACT(EPOCH FROM (NOW() - COALESCE(last_cycle_at, spawned_at)))/60 AS mins_since_cycle "
            "FROM businesses WHERE status='active' "
            "ORDER BY fitness_score DESC, spawned_at"
        )]
        # Recent leads (24h)
        out["leads"] = [dict(r) for r in await conn.fetch(
            "SELECT business_id, email, source, captured_at "
            "FROM business_leads "
            "WHERE captured_at > NOW() - INTERVAL '7 days' "
            "ORDER BY captured_at DESC LIMIT 20"
        )]
        # Real revenue (24h)
        out["revenue"] = [dict(r) for r in await conn.fetch(
            "SELECT business_id, amount_gbp, source, external_id, recorded_at "
            "FROM business_revenue "
            "WHERE is_self_paid = FALSE "
            "AND recorded_at > NOW() - INTERVAL '7 days' "
            "ORDER BY recorded_at DESC LIMIT 20"
        )]
        # Recent artifact-producing successful skill calls (12h)
        out["recent_publishes"] = [dict(r) for r in await conn.fetch(
            "SELECT skill_name, business_id, called_at "
            "FROM skill_calls "
            "WHERE ok = TRUE AND business_id IS NOT NULL "
            "AND skill_name IN ("
            "  'bluesky_post','mastodon_post','dev_to_publish','medium_publish',"
            "  'substack_publish','hashnode_publish','rss_publish','x_post',"
            "  'linkedin_post','reddit_submit'"
            ") "
            "AND called_at > NOW() - INTERVAL '12 hours' "
            "ORDER BY called_at DESC LIMIT 20"
        )]
        # Recent failures (12h, attributed)
        out["recent_failures"] = [dict(r) for r in await conn.fetch(
            "SELECT skill_name, error, COUNT(*) AS n "
            "FROM skill_calls "
            "WHERE ok = FALSE AND business_id IS NOT NULL "
            "AND called_at > NOW() - INTERVAL '12 hours' "
            "GROUP BY skill_name, error "
            "ORDER BY n DESC LIMIT 10"
        )]
        # Totals (all time, real only)
        totals = await conn.fetchrow(
            "SELECT "
            "(SELECT COUNT(*) FROM business_leads) AS leads_total, "
            "(SELECT COUNT(*) FROM business_revenue WHERE NOT is_self_paid) AS revenue_rows, "
            "(SELECT COALESCE(SUM(amount_gbp), 0) FROM business_revenue WHERE NOT is_self_paid) AS revenue_total, "
            "(SELECT COUNT(*) FROM business_templates) AS templates, "
            "(SELECT COUNT(*) FROM businesses WHERE status='active') AS active_biz, "
            "(SELECT COUNT(*) FROM businesses WHERE status='killed') AS killed_biz"
        )
        out["totals"] = dict(totals) if totals else {}

    # Credential vault status (per-service completeness)
    out["creds"] = _credential_status()
    return out


def _credential_status() -> list[dict]:
    """Per-platform: have we got the secrets needed for autonomous posting?"""
    services = {
        "bluesky": ["BSKY_HANDLE", "BSKY_APP_PASSWORD"],
        "mastodon": ["MASTODON_INSTANCE", "MASTODON_ACCESS_TOKEN"],
        "devto": ["DEVTO_API_KEY"],
        "hashnode": ["HASHNODE_PAT", "HASHNODE_PUBLICATION_ID"],
        "medium": ["MEDIUM_INTEGRATION_TOKEN", "MEDIUM_USER_ID"],
        "substack": ["SUBSTACK_EMAIL", "SUBSTACK_PASSWORD", "SUBSTACK_PUBLICATION_URL"],
    }
    if ACCOUNTS_STORE is None:
        return [{"service": s, "have": [], "missing": needed, "complete": False}
                for s, needed in services.items()]
    have_names: set[str] = set()
    try:
        have_names = set(ACCOUNTS_STORE.list_secret_names())
    except Exception:
        pass
    out = []
    for service, needed in services.items():
        have = [n for n in needed if n in have_names]
        missing = [n for n in needed if n not in have_names]
        out.append({
            "service": service, "have": have, "missing": missing,
            "complete": not missing,
        })
    return out


def _render(data: dict) -> str:
    t = data["totals"]
    rev_total = float(t.get("revenue_total", 0) or 0)
    biz_rows = "\n".join(_render_biz(b) for b in data["businesses"]) or "<tr><td colspan=6 class=muted>none active</td></tr>"
    leads_rows = "\n".join(_render_lead(l) for l in data["leads"]) or "<tr><td colspan=3 class=muted>0 captured</td></tr>"
    rev_rows = "\n".join(_render_rev(r) for r in data["revenue"]) or "<tr><td colspan=4 class=muted>0 real customer £ to date</td></tr>"
    pub_rows = "\n".join(_render_pub(p) for p in data["recent_publishes"]) or "<tr><td colspan=3 class=muted>no successful artifact-producing calls in last 12h</td></tr>"
    fail_rows = "\n".join(_render_fail(f) for f in data["recent_failures"]) or "<tr><td colspan=3 class=muted>0 failures</td></tr>"
    cred_rows = "\n".join(_render_cred(c) for c in data["creds"])
    return f"""<!doctype html>
<html lang=en><head>
<meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>swarm — {rev_total:.2f}£</title>
<meta http-equiv=refresh content=30>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
       max-width: 880px; margin: 24px auto; padding: 0 16px; color: #222;
       background: #fafafa; }}
h1 {{ font-size: 20px; margin: 0 0 4px; }}
h2 {{ font-size: 14px; text-transform: uppercase; letter-spacing: 0.06em;
     color: #666; margin: 22px 0 6px; border-bottom: 1px solid #ddd;
     padding-bottom: 4px; }}
.kpis {{ display: flex; gap: 12px; margin: 12px 0 18px; flex-wrap: wrap; }}
.kpi {{ background: white; border: 1px solid #ddd; border-radius: 6px;
       padding: 10px 14px; min-width: 110px; }}
.kpi .v {{ font-size: 22px; font-weight: 700; }}
.kpi .l {{ font-size: 11px; color: #666; text-transform: uppercase;
          letter-spacing: 0.05em; }}
.kpi.zero .v {{ color: #aaa; }}
.kpi.pos .v {{ color: #1c6ea4; }}
table {{ width: 100%; border-collapse: collapse; background: white;
        border: 1px solid #ddd; border-radius: 4px; font-size: 13px; }}
th, td {{ text-align: left; padding: 6px 10px; border-bottom: 1px solid #eee; }}
th {{ background: #f4f4f4; font-weight: 600; }}
td.muted {{ color: #999; font-style: italic; text-align: center; padding: 12px; }}
td.ok {{ color: #1c6ea4; font-weight: 600; }}
td.fail {{ color: #c44; }}
.cred-ok {{ color: #1c6ea4; font-weight: 600; }}
.cred-miss {{ color: #c44; }}
small {{ color: #888; }}
.refresh-note {{ font-size: 11px; color: #888; margin: 20px 0; text-align: center; }}
</style>
</head><body>
<h1>swarm — autonomous status</h1>
<div class=kpis>
  <div class="kpi {'pos' if rev_total > 0 else 'zero'}">
    <div class=v>£{rev_total:.2f}</div><div class=l>real revenue</div>
  </div>
  <div class="kpi {'pos' if int(t.get('revenue_rows', 0) or 0) > 0 else 'zero'}">
    <div class=v>{int(t.get('revenue_rows', 0) or 0)}</div><div class=l>paid customers</div>
  </div>
  <div class="kpi {'pos' if int(t.get('leads_total', 0) or 0) > 0 else 'zero'}">
    <div class=v>{int(t.get('leads_total', 0) or 0)}</div><div class=l>leads</div>
  </div>
  <div class=kpi>
    <div class=v>{int(t.get('active_biz', 0) or 0)}</div><div class=l>active biz</div>
  </div>
  <div class=kpi>
    <div class=v>{int(t.get('templates', 0) or 0)}</div><div class=l>graduated genomes</div>
  </div>
</div>

<h2>businesses</h2>
<table>
<tr><th>name</th><th>niche</th><th>fit</th><th>£</th><th>stall</th><th>age (h) / last cycle (m)</th></tr>
{biz_rows}
</table>

<h2>recent successful publishes (12h)</h2>
<table>
<tr><th>skill</th><th>business</th><th>when</th></tr>
{pub_rows}
</table>

<h2>recent leads (7d)</h2>
<table>
<tr><th>email</th><th>source</th><th>when</th></tr>
{leads_rows}
</table>

<h2>recent real customer revenue (7d)</h2>
<table>
<tr><th>amount</th><th>source</th><th>charge id</th><th>when</th></tr>
{rev_rows}
</table>

<h2>recent failures (12h, business-attributed)</h2>
<table>
<tr><th>skill</th><th>error</th><th>count</th></tr>
{fail_rows}
</table>

<h2>credential status</h2>
<table>
<tr><th>service</th><th>status</th><th>have</th><th>missing</th></tr>
{cred_rows}
</table>

<div class=refresh-note>auto-refresh every 30s · <a href="/api/state">/api/state</a> · <a href="/">/dashboard</a></div>
</body></html>"""


def _render_biz(b: dict) -> str:
    md = b.get("metadata") or {}
    if isinstance(md, str):
        md = json.loads(md)
    stall = (md or {}).get("artifact_stall_count", 0)
    age_h = float(b.get("age_h") or 0)
    mins_ago = float(b.get("mins_since_cycle") or 0)
    return (
        f"<tr><td>{_esc(b['name'])}</td>"
        f"<td><small>{_esc(str(b['niche'])[:60])}</small></td>"
        f"<td>{float(b['fitness_score']):.2f}</td>"
        f"<td>£{float(b['revenue_total_gbp']):.2f}</td>"
        f"<td>{stall}</td>"
        f"<td>{age_h:.1f}h / {mins_ago:.0f}m</td></tr>"
    )


def _render_lead(l: dict) -> str:
    return (
        f"<tr><td>{_esc(l['email'])}</td>"
        f"<td><small>{_esc(l['source'])}</small></td>"
        f"<td><small>{_esc(str(l['captured_at']))[:19]}</small></td></tr>"
    )


def _render_rev(r: dict) -> str:
    return (
        f"<tr><td class=ok>£{float(r['amount_gbp']):.2f}</td>"
        f"<td>{_esc(r['source'])}</td>"
        f"<td><small>{_esc(str(r['external_id']))[:30]}</small></td>"
        f"<td><small>{_esc(str(r['recorded_at']))[:19]}</small></td></tr>"
    )


def _render_pub(p: dict) -> str:
    return (
        f"<tr><td class=ok>{_esc(p['skill_name'])}</td>"
        f"<td><small>{_esc(str(p['business_id'])[:12])}</small></td>"
        f"<td><small>{_esc(str(p['called_at']))[:19]}</small></td></tr>"
    )


def _render_fail(f: dict) -> str:
    return (
        f"<tr><td class=fail>{_esc(f['skill_name'])}</td>"
        f"<td><small>{_esc(str(f['error'] or '?')[:140])}</small></td>"
        f"<td>{int(f['n'])}</td></tr>"
    )


def _render_cred(c: dict) -> str:
    cls = "cred-ok" if c["complete"] else "cred-miss"
    status = "✓ ready" if c["complete"] else "✗ missing"
    have = ", ".join(c["have"]) if c["have"] else "—"
    missing = ", ".join(c["missing"]) if c["missing"] else "—"
    return (
        f"<tr><td>{c['service']}</td>"
        f"<td class={cls}>{status}</td>"
        f"<td><small>{_esc(have)}</small></td>"
        f"<td><small>{_esc(missing)}</small></td></tr>"
    )


def _esc(s: Any) -> str:
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))
