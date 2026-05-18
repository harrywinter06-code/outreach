# Phase H — Session C: Infrastructure + Finance + Launch + Support + Compliance

> **Paste this entire document as the first message of a fresh Claude Code session in `C:\Users\Winte\clawbot`.**

## Mission

You are running **Session C of 3** in a parallel push to ship Phase H of clawbot's self-extending skill system. Phase H is the bootstrap skill library — 14 tasks, ~139 skills, currently 0 shipped. Your slice is the infrastructure + operations half: 5 tasks, ~52 skills, that lets clawbot manage its own UK-Ltd ops, launch on third-party platforms, deploy code, handle support, and stay compliant.

## Context (read these first, in order)

1. `docs/superpowers/plans/2026-05-17-self-extending-skill-system.md` — the master Phase H plan. Read **lines 4140–4184 (Task 26 Finance) + lines 4259–4280 (Task 28 Launches) + lines 4515–4585 (Task 35 Dev) + lines 4589–4626 (Tasks 36 Support, 37 Compliance)**.
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
git checkout -b feat/phase-h-infra origin/master
```

Verify you're on the latest master:
```bash
git log --oneline -5
# Should show: feat: seed H1, feat: board PIVOT, feat: active_hypothesis, fix: thread db_pool, feat: plans injected
```

## Your assignment — 5 tasks, ~52 skills

| Task | Pack | Directory | Skills |
|---|---|---|---|
| 26 | Finance + UK-gov | `agents/skills/_builtin/finance/` | 11 |
| 28 | Third-party launches | `agents/skills/_builtin/launch/` | 10 |
| 35 | Dev / infra | `agents/skills/_builtin/dev/` | 14 |
| 36 | Customer comms + support | `agents/skills/_builtin/support/` | 6 |
| 37 | Risk + compliance | `agents/skills/_builtin/compliance/` | 11 |

### Task 26 skills (master plan lines 4140–4181)
`companies_house_search`, `companies_house_get_company`, `companies_house_get_officers`, `companies_house_get_filings`, `companies_house_monitor_filings`, `hmrc_check_vat_number`, `freeagent_create_invoice`, `freeagent_record_expense`, `xero_reconcile_transaction`, `compute_runway_months`, `ir35_determine_status`.

No new ctx surface — composes `ctx.http`, `ctx.sql`. `compute_runway_months` is pure-math; `ir35_determine_status` is embedded CEST rules (no external call).

### Task 28 skills (master plan lines 4259–4280)
`producthunt_schedule`, `betalist_submit`, `indiehackers_post`, `hn_show_submit`, `directory_submit_g2`, `directory_submit_capterra`, `directory_submit_alternative_to`, `haro_respond`, `prnewswire_submit`, `podcast_pitch`.

No new ctx surface — composes `ctx.browser`, `ctx.email`, `ctx.http`. Most of these are browser-driven (no APIs).

### Task 35 skills (master plan lines 4515–4585)
`github_create_repo`, `github_create_release`, `github_star_repo`, `github_search_issues`, `npm_publish`, `pypi_publish`, `docker_build_and_push`, `dns_set_record`, `dns_verify_propagation`, `ssl_check_expiry`, `domain_check_availability`, `domain_register`, `cloudflare_purge_cache`, `cloudflare_deploy_pages_site`.

**Requires new `ctx.dev` surface in `skill_ctx.py`** — add a `DevClient` Protocol with `exec_allowed_command(cmd_name, args, cwd)`. Allowlist: `npm_publish, pip_wheel, twine_upload, docker_build, docker_push, docker_tag, git_push, git_clone`. Live impl uses `subprocess.run` via `asyncio.to_thread`, gated by the allowlist + a path-traversal check on `cwd`. **See master plan Task 35b (lines 4535–4577) for the exact implementation pattern — copy that code.**

`domain_register` has `requires_approval: True` in its META (operator-gated, like `stripe_issue_card`).

### Task 36 skills (master plan lines 4589–4602)
`support_send_email_reply`, `support_assign_ticket`, `support_canned_response`, `chat_widget_respond_live`, `calendar_book_slot`, `survey_send_nps`.

No new ctx surface — composes `ctx.email`, `ctx.sql`, `ctx.vector`, `ctx.bus`, `ctx.http`.

**Schema note:** add a `tickets` table to `db.py:init_schema()`. Minimal shape:
```sql
CREATE TABLE IF NOT EXISTS tickets (
    id TEXT PRIMARY KEY,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    assigned_to TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### Task 37 skills (master plan lines 4607–4626)
`sanctions_check`, `kyc_verify_address`, `fraud_score_transaction`, `captcha_solve`, `gdpr_data_export`, `gdpr_delete_user`, `tos_generate`, `privacy_policy_generate`, `dmca_takedown_request`, `esign_send`, `dispute_respond`.

No new ctx surface — composes `ctx.http`, `ctx.llm`, `ctx.sql`, `ctx.email`, `ctx.payments` (for `dispute_respond`).

`gdpr_delete_user` has `requires_approval: True`.

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
- AST scanner forbids: `import os`, `subprocess`, `socket`, `httpx` directly. Use only `ctx.*` clients. (Exception: `ctx.dev._LiveDev` internally uses subprocess — that's fine because it's the ctx implementation, not skill code.)

**Test pattern per pack** — see Session A's handoff for the exact template (one pack-load test + one representative call).

**Builtin skills test extension** — at the end of each pack task, add the new skill names to `EXPECTED_BUILTINS` in `tests/test_builtin_skills.py`.

**Commit message format**:
```
git commit -m "feat: <pack> skill pack (N skills)" -m "" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

## Execution

Use the **subagent-driven-development** skill. One subagent per task (5 subagents). After each, dispatch a spec-compliance reviewer then a quality reviewer.

Model selection:
- Implementer: **sonnet** for Task 35 (new ctx.dev surface, security-sensitive allowlist) and Task 37 (compliance — `requires_approval` skills + GDPR deletion need care). **haiku** for Tasks 26/28/36 (mostly compositional).
- Spec reviewer: **haiku**
- Quality reviewer: **sonnet**

Task order (sequential):
1. Task 36 — Support pack (smallest, validates pattern, simple SQL + email)
2. Task 28 — Third-party launches (all browser-driven; no new infra)
3. Task 26 — Finance + UK-gov (Companies House API + pure-math runway/IR35)
4. Task 35 — Dev/infra **WITH ctx.dev surface** (most complex; needs Task 35b first)
5. Task 37 — Compliance (uses Stripe Radar + LLM gen + requires_approval flags)

## Coordination with Sessions A and B

You all branch from the same `master` commit. The three branches will conflict in **three specific places** when merged back. The user resolves these manually:

| File | Conflict region | Resolution |
|---|---|---|
| `src/clawbot/skill_ctx.py` | `class SkillCtx:` field list — each session adds one new field (`revenue`, `media`, `dev`) | Keep all three insertions |
| `src/clawbot/skill_ctx.py` | `make_noop_ctx` SkillCtx(...) kwargs | Same — keep all |
| `src/clawbot/skill_ctx.py` | `make_live_ctx` SkillCtx(...) kwargs | Same — keep all |
| `tests/test_builtin_skills.py` | `EXPECTED_BUILTINS` set literal | Union of all three sets |

**Your ctx surface ownership:** `ctx.dev` (only). Don't add `ctx.revenue` or `ctx.media` — Sessions A and B own those.

**Important — `ctx.dev` is security-sensitive.** The allowlist-based command exec from master plan Task 35b is the right design — DO NOT widen the allowlist, DO NOT skip the path-traversal check on `cwd`, DO NOT permit shell interpolation. Skills compose this surface but the surface itself is the trust boundary. If you find yourself needing a command not in the allowlist, stop and escalate — don't add to the list silently.

**Other parallel safety:**
- Each session creates files under its own `_builtin/<domain>/` directories — no overlap.
- New tests in new files — no overlap.
- `db.py` migrations — Session C adds `tickets`. Session A adds `leads` + `suppression`. Session B adds `experiments` + `experiment_observations`. Append-only — no conflict.

## Acceptance criteria (binary — all must pass, then stop)

- [ ] `agents/skills/_builtin/finance/`, `_builtin/launch/`, `_builtin/dev/`, `_builtin/support/`, `_builtin/compliance/` directories exist with correct skill files
- [ ] All 52 new skills load via `SkillRegistry.discover()` (verified by the per-pack `test_<pack>_loads` tests)
- [ ] `tests/test_builtin_skills.py::test_all_expected_builtins_load` includes all 52 new names and passes
- [ ] `ctx.dev` surface (`DevClient` Protocol + `_NoopDev` + `_LiveDev` with allowlist + cwd guard) exists in `skill_ctx.py`; `make_noop_ctx` and `make_live_ctx` both wire it
- [ ] `tickets` table added to `db.py` schema-init
- [ ] `requires_approval: True` set on `domain_register` (Task 35) and `gdpr_delete_user` (Task 37)
- [ ] Full suite: ≥ previous pass count + 10 new test files. Only failures are the 2 pre-existing asyncpg ones.
- [ ] Branch `feat/phase-h-infra` pushed to `origin`.

When all pass: stop. Report the branch name and the 5 commit SHAs.

## When you're done

1. Push: `git push origin feat/phase-h-infra`
2. Reply: "DONE — branch `feat/phase-h-infra`, 5 commits (SHAs), ~52 skills, all tests green except the 2 known asyncpg ones."
3. Do not merge to master — the user merges all three session branches sequentially with manual conflict resolution.
