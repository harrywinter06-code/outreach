# Phase H — Session B: Research + Experiments + Browser + Media + SEO

> **Paste this entire document as the first message of a fresh Claude Code session in `C:\Users\Winte\clawbot`.**

## Mission

You are running **Session B of 3** in a parallel push to ship Phase H of clawbot's self-extending skill system. Phase H is the bootstrap skill library — 14 tasks, ~139 skills, currently 0 shipped. Your slice is the discovery + experimentation half: 5 tasks, ~44 skills, that lets clawbot find opportunities, browse the web, run media generation, and measure what works.

## Context (read these first, in order)

1. `docs/superpowers/plans/2026-05-17-self-extending-skill-system.md` — the master Phase H plan. Read **lines 4337–4677 (Tasks 30 SEO, 32 Media, 33 Intel, 34 Browser, 38 Experiment)**.
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
git checkout -b feat/phase-h-research origin/master
```

Verify you're on the latest master with all OODA-loop work landed:
```bash
git log --oneline -5
# Should show: feat: seed H1, feat: board PIVOT, feat: active_hypothesis, fix: thread db_pool, feat: plans injected
```

## Your assignment — 5 tasks, ~44 skills

| Task | Pack | Directory | Skills |
|---|---|---|---|
| 30 | SEO + organic discovery | `agents/skills/_builtin/seo/` | 10 |
| 32 | Media extras | `agents/skills/_builtin/media_extras/` | 9 |
| 33 | Research + intelligence | `agents/skills/_builtin/intel/` | 11 |
| 34 | Browser-driven generic primitives | `agents/skills/_builtin/browser/` | 8 |
| 38 | Experiment + learning | `agents/skills/_builtin/experiment/` | 6 |

### Task 30 skills (master plan lines 4337–4355)
`gsc_query`, `bing_webmaster_query`, `serp_check`, `keyword_research`, `backlink_audit`, `sitemap_generate`, `sitemap_submit`, `schema_org_generate`, `lighthouse_audit`, `robots_txt_check`.

No new ctx surface — composes `ctx.http`, `ctx.fs`.

### Task 32 skills (master plan lines 4417–4434)
`video_generate`, `video_subtitle`, `video_dub`, `podcast_generate`, `logo_generate`, `favicon_generate`, `image_remove_bg`, `image_upscale`, `screenshot_annotate`.

**Requires new `ctx.media` surface in `skill_ctx.py`** — add a `MediaClient` Protocol + `_NoopMedia` + `_LiveMedia` (wraps Runway/Pika/ElevenLabs/Remove.bg/Stability httpx calls + Pillow for `screenshot_annotate`). Follow the same pattern as `_LiveSearch`.

The plan's Task 22 (earlier in Phase G) was the original `ctx.media` for `image_generate`/`tts_generate`/`screenshot_url`/`stitch_audio`. **Check if `ctx.media` already exists in `skill_ctx.py`** — if it does, you only EXTEND it; if not, you create it. The new Phase H methods to add are: `video_generate`, `video_subtitle`, `video_dub`, `image_remove_bg`, `image_upscale`, `stitch_audio` (if missing), `tts_generate` (if missing — used by `podcast_generate`), `image_generate` (if missing — used by `logo_generate`), `screenshot_url` (if missing — used by `screenshot_annotate`).

### Task 33 skills (master plan lines 4438–4488)
`web_deep_research`, `web_diff_page`, `news_monitor_topic`, `social_listen_brand`, `competitor_pricing_scrape`, `github_trending`, `arxiv_search`, `arxiv_summarize`, `reviews_scrape_g2`, `glassdoor_scrape_company`, `crunchbase_lookup`.

No new ctx surface — composes `ctx.http`, `ctx.browser`, `ctx.llm`, `ctx.fs`. `web_deep_research` composes `web_search` (already exists from 100-hands).

### Task 34 skills (master plan lines 4493–4510)
`browser_signup`, `browser_form_fill`, `browser_extract_structured`, `browser_solve_captcha`, `browser_save_session`, `browser_load_session`, `browser_navigate_and_record`, `browser_screenshot_element`.

No new ctx surface — composes `ctx.browser` + `ctx.fs` (sessions stored at `data/sessions/<name>.json`).

### Task 38 skills (master plan lines 4630–4675)
`experiment_create`, `experiment_record_observation`, `experiment_compute_significance`, `bandit_allocate_budget`, `experiment_kill_underperformer`, `experiment_summarize`.

No new ctx surface — composes `ctx.sql`, `ctx.llm`. `experiment_compute_significance` is pure-stdlib (two-proportion z-test).

**Schema note:** add `experiments` + `experiment_observations` tables to `db.py:init_schema()`. The plan's Task 38 doesn't spec this explicitly — define minimal tables yourself:
```sql
CREATE TABLE IF NOT EXISTS experiments (
    id TEXT PRIMARY KEY,
    hypothesis TEXT NOT NULL,
    metric TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    cutoff_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS experiment_observations (
    id BIGSERIAL PRIMARY KEY,
    experiment_id TEXT NOT NULL REFERENCES experiments(id),
    arm TEXT NOT NULL,
    success BOOLEAN NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

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

**Test pattern per pack** — see Session A's handoff for the exact template (one pack-load test + one representative call).

**Builtin skills test extension** — at the end of each pack task, add the new skill names to `EXPECTED_BUILTINS` in `tests/test_builtin_skills.py`.

**Commit message format**:
```
git commit -m "feat: <pack> skill pack (N skills)" -m "" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

## Execution

Use the **subagent-driven-development** skill. One subagent per task (5 subagents). After each, dispatch a spec-compliance reviewer then a quality reviewer.

Model selection:
- Implementer: **sonnet** for Tasks 32 (ctx.media surface) and 34 (browser primitives), **haiku** for Tasks 30/33/38 (mostly compositional)
- Spec reviewer: **haiku**
- Quality reviewer: **sonnet**

Task order (sequential — pick the one with the smallest dependency surface first):
1. Task 38 — Experiment (pure stdlib + simple SQL; validates the pattern)
2. Task 34 — Browser primitives (foundation for many other tasks)
3. Task 30 — SEO (composes http + fs)
4. Task 33 — Research/intel (uses browser primitives from Task 34 indirectly)
5. Task 32 — Media extras (new/extended ctx.media surface — biggest chunk; do last)

## Coordination with Sessions A and C

You all branch from the same `master` commit. The three branches will conflict in **three specific places** when merged back. The user resolves these manually:

| File | Conflict region | Resolution |
|---|---|---|
| `src/clawbot/skill_ctx.py` | `class SkillCtx:` field list — each session adds one new field (`revenue`, `media`, `dev`) | Keep all three insertions |
| `src/clawbot/skill_ctx.py` | `make_noop_ctx` SkillCtx(...) kwargs | Same — keep all |
| `src/clawbot/skill_ctx.py` | `make_live_ctx` SkillCtx(...) kwargs | Same — keep all |
| `tests/test_builtin_skills.py` | `EXPECTED_BUILTINS` set literal | Union of all three sets |

**Your ctx surface ownership:** `ctx.media` (only). Don't add `ctx.revenue` or `ctx.dev` — Sessions A and C own those.

**Important — `ctx.media` may already partly exist:**
The master plan's Task 22 (Phase G, earlier) introduced `ctx.media` for image/tts/screenshot primitives. **Read `src/clawbot/skill_ctx.py` first** and search for `MediaClient` or `class _LiveMedia`. If it exists, you EXTEND it (add the new methods listed under Task 32 above). If it doesn't, you CREATE it with all the methods Task 32 needs plus the bridge methods Task 32 composes from (`image_generate`, `tts_generate`, `screenshot_url`, `stitch_audio`).

**Other parallel safety:**
- Each session creates files under its own `_builtin/<domain>/` directories — no overlap.
- New tests in new files — no overlap.
- `db.py` migrations — Session B adds `experiments` + `experiment_observations`. Session A adds `leads` + `suppression`. Session C might add `tickets`. Append-only — no conflict.

## Acceptance criteria (binary — all must pass, then stop)

- [ ] `agents/skills/_builtin/seo/`, `_builtin/media_extras/`, `_builtin/intel/`, `_builtin/browser/`, `_builtin/experiment/` directories exist with correct skill files
- [ ] All 44 new skills load via `SkillRegistry.discover()` (verified by the per-pack `test_<pack>_loads` tests)
- [ ] `tests/test_builtin_skills.py::test_all_expected_builtins_load` includes all 44 new names and passes
- [ ] `ctx.media` surface exists in `skill_ctx.py` with all Task 32 methods + composed bridges; `make_noop_ctx` and `make_live_ctx` both wire it
- [ ] `experiments` + `experiment_observations` tables added to `db.py` schema-init
- [ ] Full suite: ≥ previous pass count + 10 new test files. Only failures are the 2 pre-existing asyncpg ones.
- [ ] Branch `feat/phase-h-research` pushed to `origin`.

When all pass: stop. Report the branch name and the 5 commit SHAs.

## When you're done

1. Push: `git push origin feat/phase-h-research`
2. Reply: "DONE — branch `feat/phase-h-research`, 5 commits (SHAs), ~44 skills, all tests green except the 2 known asyncpg ones."
3. Do not merge to master — the user merges all three session branches sequentially with manual conflict resolution.
