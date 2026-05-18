# Phase H — Session A: Commercial Path (Revenue + Publishing + Outreach + Writing)

> **Paste this entire document as the first message of a fresh Claude Code session in `C:\Users\Winte\clawbot`.**

## Mission

You are running **Session A of 3** in a parallel push to ship Phase H of clawbot's self-extending skill system. Phase H is the bootstrap skill library — 14 tasks, ~139 skills, currently 0 shipped. Your slice is the commercial path: 4 tasks, ~43 skills, that lets clawbot run the revenue side of any hypothesis (sell things, publish content, do outreach, write copy).

## Context (read these first, in order)

1. `docs/superpowers/plans/2026-05-17-self-extending-skill-system.md` — the master Phase H plan. Read **lines 4033–4255 (Task 25 Revenue) + lines 4283–4334 (Task 29 Outreach) + lines 4185–4256 (Task 27 Publishing) + lines 4359–4413 (Task 31 Writing)**.
2. `C:\ClaudeShared\memory\projects\clawbot\operating_facts.md` — VPS, deploy, runbook. Read the OODA-loop closure section at the bottom.
3. `C:\ClaudeShared\memory\projects\clawbot\skillctx_is_extension_seam.md` — architectural memory; `SkillCtx` is the only extension seam for external integrations.

## Pre-flight

- Repo root: `C:\Users\Winte` (multi-project; only modify files under `clawbot/`).
- Git toplevel: `git rev-parse --show-toplevel` returns `C:/Users/Winte`. All your commits will be on a feature branch off `master`.
- Tests: `uv run pytest` from `C:\Users\Winte\clawbot`.
- Pre-existing local-only failures: 2 in `tests/test_causal_store.py` (asyncpg unavailable locally). Same for `tests/test_plan_store.py` and `tests/test_hypothesis_store.py` — they SKIP locally. Don't try to fix these. Total expected: 519 pass + 9 skip after your work, plus the new tests you add.

## Branch setup (do this first, before any code)

```bash
cd /c/Users/Winte
git fetch origin master
git checkout -b feat/phase-h-commercial origin/master
```

Verify you're on the latest master with all OODA-loop work landed:
```bash
git log --oneline -5
# Should show: feat: seed H1, feat: board PIVOT, feat: active_hypothesis, fix: thread db_pool, feat: plans injected
```

## Your assignment — 4 tasks, ~43 skills

| Task | Pack | Directory | Skills |
|---|---|---|---|
| 25 | Revenue | `agents/skills/_builtin/revenue/` | 11 |
| 27 | Owned-channel publishing | `agents/skills/_builtin/publish/` | 10 |
| 29 | Cold outreach + CRM | `agents/skills/_builtin/outreach/` | 11 |
| 31 | Writing | `agents/skills/_builtin/write/` | 11 |

### Task 25 skills (master plan lines 4041–4137)
`gumroad_list_products`, `gumroad_sales_last_7d`, `gumroad_get_sale`, `paypal_create_order`, `paypal_capture_order`, `paypal_list_transactions`, `crypto_generate_receive_address`, `crypto_check_balance`, `stripe_subscription_create`, `stripe_subscription_cancel`, `revenue_aggregate_today_gbp`.

**Requires new `ctx.revenue` surface in `skill_ctx.py`** — add a `RevenueClient` Protocol + `_NoopRevenue` + `_LiveRevenue` (wraps existing `clawbot.gumroad.GumroadClient` + new PayPal/Coinbase httpx calls). Follow the same pattern as `_LiveSearch` (added earlier this week).

### Task 27 skills (master plan lines 4185–4256)
`substack_publish`, `medium_publish`, `dev_to_publish`, `hashnode_publish`, `bluesky_post`, `mastodon_post`, `rss_publish`, `buffer_schedule`, `newsletter_send`, `youtube_upload`.

No new ctx surface — composes existing `ctx.browser`, `ctx.http`, `ctx.email`, `ctx.fs`.

### Task 29 skills (master plan lines 4283–4334)
`hunter_find_email`, `apollo_search_contacts`, `email_warmup_send`, `email_warmup_inbox_clean`, `email_send_cold`, `email_send_followup_sequence`, `email_classify_reply`, `email_suppress`, `crm_upsert_lead`, `crm_advance_stage`, `lead_score`.

No new ctx surface — composes `ctx.email`, `ctx.http`, `ctx.sql`, `ctx.llm`, `ctx.fs`.

**Schema note:** add `leads` + `suppression` tables to `db.py:init_schema()` in your first commit (allowlisted DDL, idempotent `CREATE TABLE IF NOT EXISTS`). The skill plan's Task 29 Step 4 covers this.

### Task 31 skills (master plan lines 4359–4413)
`write_long_form_article`, `write_tweet_thread`, `write_linkedin_post`, `write_cold_email`, `write_landing_page_copy`, `write_case_study`, `summarize`, `translate`, `grammar_check`, `readability_score`, `tone_rewrite`.

No new ctx surface — composes `ctx.llm` + pure stdlib (`readability_score` is pure Flesch-Kincaid).

## Patterns to follow (from prior session work)

**Skill file format** — example: `agents/skills/_builtin/payments/stripe_create_product.py`:
```python
META = {
    "name": "stripe_create_product", "builtin": True,
    "description": "Create a Stripe product. Returns the product id for use in create_price.",
    "params": {"name": "str", "description": "str"},
    "returns": {"id": "str", "name": "str"},
}

async def run(ctx, name: str, description: str) -> dict:
    return await ctx.payments.create_product(name=name, description=description)
```
- Module-level `META` dict (don't subclass `SkillMeta`).
- `async def run(ctx, ...) -> dict` returning dict whose keys match `META["returns"]`.
- ~15-25 lines per skill. No business logic in the skill — delegate to `ctx`.
- AST scanner forbids: `import os`, `subprocess`, `socket`, `httpx` directly. Use only `ctx.*` clients.

**Test pattern per pack** — example: `tests/test_payments_ctx.py`:
```python
import asyncio
from pathlib import Path
from clawbot.skill_registry import SkillRegistry
from clawbot.skill_ctx import make_noop_ctx

PACK_DIR = Path(__file__).parent.parent / "agents" / "skills" / "_builtin" / "revenue"


def test_revenue_pack_loads():
    reg = SkillRegistry(skills_dir=PACK_DIR)
    reg.discover()
    names = set(reg.list_names())
    expected = {"gumroad_list_products", ...}  # all 11
    missing = expected - names
    assert not missing, f"missing: {missing}"


def test_one_representative_skill_runs():
    reg = SkillRegistry(skills_dir=PACK_DIR)
    reg.discover()
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    rec = asyncio.run(reg.call("revenue_aggregate_today_gbp", {}, ctx))
    assert rec.ok
```
Don't try to test every skill exhaustively — one pack-load test + one representative call is enough. Real coverage comes from canary mode after deploy.

**Builtin skills test extension** — at the end of each pack task, add the new skill names to `EXPECTED_BUILTINS` in `tests/test_builtin_skills.py`.

**Commit message format** — exactly as the master plan suggests:
```
git commit -m "feat: revenue skill pack (11 skills)" -m "" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

## Execution

Use the **subagent-driven-development** skill. One subagent per task (4 subagents). After each, dispatch a spec-compliance reviewer then a quality reviewer (same pattern as the OODA-loop work earlier this week).

Model selection:
- Implementer for each pack: **sonnet** (each pack is ~10 small files but the new `ctx.revenue` surface in Task 25 needs more care)
- Spec reviewer: **haiku**
- Quality reviewer: **sonnet**

Task order (sequential, since each builds on the previous in terms of conventions):
1. Task 31 — Writing pack first (pure-stdlib-ish, no new ctx, fastest validation of pattern)
2. Task 25 — Revenue pack (new ctx.revenue surface — biggest chunk)
3. Task 27 — Publishing pack (uses browser/http/email)
4. Task 29 — Outreach + CRM (DB tables + classification)

## Coordination with Sessions B and C

You all branch from the same `master` commit. The three branches will conflict in **three specific places** when merged back. The user resolves these manually:

| File | Conflict region | Resolution |
|---|---|---|
| `src/clawbot/skill_ctx.py` | `class SkillCtx:` field list — each session adds one new field (`revenue`, `media`, `dev`) | Keep all three insertions |
| `src/clawbot/skill_ctx.py` | `make_noop_ctx` SkillCtx(...) kwargs | Same — keep all |
| `src/clawbot/skill_ctx.py` | `make_live_ctx` SkillCtx(...) kwargs | Same — keep all |
| `tests/test_builtin_skills.py` | `EXPECTED_BUILTINS` set literal | Union of all three sets |

**Your ctx surface ownership:** `ctx.revenue` (only). Don't add `ctx.media` or `ctx.dev` — Sessions B and C own those.

**Other parallel safety:**
- Each session creates files under its own `_builtin/<domain>/` directories — no overlap there.
- New tests in new files — no overlap.
- `db.py` migrations — Session A adds `leads` + `suppression` tables (Task 29). Session B adds nothing. Session C might add a `tickets` table (Task 36 in their slice). Append-only — no conflict.

## Acceptance criteria (binary — all must pass, then stop)

- [ ] `agents/skills/_builtin/revenue/`, `_builtin/publish/`, `_builtin/outreach/`, `_builtin/write/` directories exist with the correct skill files
- [ ] All 43 new skills load via `SkillRegistry.discover()` (verified by the per-pack `test_<pack>_loads` tests)
- [ ] `tests/test_builtin_skills.py::test_all_expected_builtins_load` includes all 43 new names and passes
- [ ] `ctx.revenue` surface (`RevenueClient` Protocol + Noop + Live) exists in `skill_ctx.py`; `make_noop_ctx` and `make_live_ctx` both wire it
- [ ] `leads` + `suppression` tables added to `db.py` schema-init
- [ ] Full suite: ≥ previous pass count + 8 new test files. Only failures are the 2 pre-existing asyncpg ones.
- [ ] Branch `feat/phase-h-commercial` pushed to `origin`.

When all pass: stop. Report the branch name and the 4 commit SHAs. Do not invent additional skills or refactor existing code.

## When you're done

1. Push: `git push origin feat/phase-h-commercial`
2. Reply: "DONE — branch `feat/phase-h-commercial`, 4 commits (SHAs), ~43 skills, all tests green except the 2 known asyncpg ones."
3. Do not merge to master — the user merges all three session branches sequentially with manual conflict resolution.
