"""In-memory skill registry: discover from disk, validate, call by name.

Discovery is one-shot at startup; hot-reload is added in Task 5.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from clawbot.skill_ctx import SkillCallRecord, SkillCtx, SkillMeta
from clawbot.skill_loader import SkillValidationError, load_skill_module, scan_skill_source

logger = logging.getLogger(__name__)


@dataclass
class _LoadedSkill:
    meta: SkillMeta
    run: Callable[..., Awaitable[dict[str, Any]]]
    source_path: Path


@dataclass
class _SkillStats:
    first_live_call_at: float = 0.0
    live_call_count: int = 0
    live_failure_count: int = 0


class SkillRegistry:
    def __init__(self, skills_dir: Path, archive_dir: Path | None = None) -> None:
        self._dir = skills_dir
        self._archive_dir = archive_dir
        self._skills: dict[str, _LoadedSkill] = {}
        self._stats: dict[str, _SkillStats] = {}
        self._stats_db: Any | None = None

    def set_stats_db(self, db_pool: Any) -> None:
        """Wire a database pool so every skill call is recorded in skill_calls."""
        self._stats_db = db_pool

    def discover(self) -> None:
        """Scan skills_dir, load every passing skill, log every failure."""
        if not self._dir.exists():
            logger.warning("skills_dir does not exist: %s", self._dir)
            return
        for path in sorted(self._dir.rglob("*.py")):
            if path.name.startswith("_") and path.parent.name != "_builtin":
                continue
            try:
                self._load_one(path)
            except SkillValidationError as exc:
                logger.warning("skill rejected: %s — %s", path, exc)
            except Exception as exc:
                logger.error("skill load error: %s — %s", path, exc)

    def _load_one(self, path: Path) -> None:
        source = path.read_text(encoding="utf-8")
        scan_skill_source(source)
        ns = load_skill_module(source, module_name=path.stem)
        if "META" not in ns or "run" not in ns:
            raise SkillValidationError("missing META or run after load")
        meta_dict = ns["META"]
        meta = SkillMeta(
            name=meta_dict["name"],
            description=meta_dict["description"],
            params=meta_dict.get("params", {}),
            returns=meta_dict.get("returns", {}),
            cost_estimate_usd=meta_dict.get("cost_estimate_usd", 0.0),
            requires_approval=meta_dict.get("requires_approval", False),
            timeout_s=meta_dict.get("timeout_s", 30.0),
            builtin=meta_dict.get("builtin", False) or "_builtin" in path.parts,
        )
        self._skills[meta.name] = _LoadedSkill(meta=meta, run=ns["run"], source_path=path)
        logger.info("skill loaded: %s (%s)", meta.name, path)

    def _record_live_call(self, name: str, ok: bool) -> None:
        s = self._stats.setdefault(name, _SkillStats())
        if s.live_call_count == 0:
            s.first_live_call_at = time.monotonic()
        s.live_call_count += 1
        if not ok:
            s.live_failure_count += 1

    def is_canary(self, name: str) -> bool:
        """True if skill has fewer than 3 successful live calls."""
        s = self._stats.get(name)
        if s is None:
            return True
        return (s.live_call_count - s.live_failure_count) < 3

    def demote_on_canary_failure(self, name: str, reason: str) -> None:
        """Move a failed-canary skill out of live and into archive."""
        loaded = self._skills.get(name)
        if loaded is None:
            return
        if self._archive_dir is not None:
            from datetime import datetime, UTC
            ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            archive_path = self._archive_dir / f"{name}-{ts}.canary_failed.py"
            try:
                original = loaded.source_path.read_text(encoding="utf-8")
                archive_path.write_text(
                    f"# DEMOTED: canary failure — {reason}\n{original}",
                    encoding="utf-8",
                )
                loaded.source_path.unlink()
            except Exception as exc:
                logger.error("demote_on_canary_failure: archive write failed: %s", exc)
        del self._skills[name]
        logger.warning("skill demoted (canary failure): %s — %s", name, reason)

    def list_names(self) -> list[str]:
        return sorted(self._skills.keys())

    def get_meta(self, name: str) -> SkillMeta | None:
        skill = self._skills.get(name)
        return skill.meta if skill else None

    async def _record_db_stat(
        self, record: SkillCallRecord, *, business_id: str | None = None,
    ) -> None:
        """Insert a row into skill_calls. Swallows all errors to never break callers.

        business_id (Z2.5) is pulled from the SkillCtx at call time so per-business
        activity attribution works end-to-end. NULL for executive cycles.
        """
        if self._stats_db is None:
            return
        try:
            async with self._stats_db.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO skill_calls
                        (skill_name, caller_id, ok, cost_usd, latency_ms, error, business_id)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """,
                    record.skill_name,
                    record.caller_id,
                    record.ok,
                    record.cost_usd,
                    record.latency_ms,
                    record.error,
                    business_id,
                )
        except Exception as exc:
            logger.warning("skill_calls INSERT failed: %s", exc)

    async def call(
        self,
        name: str,
        params: dict[str, Any],
        ctx: SkillCtx,
    ) -> SkillCallRecord:
        skill = self._skills.get(name)
        if skill is None:
            # Z2.5b: record the failure so activity_score_72h reflects every
            # attempt (the prior early-return bypassed _record_db_stat, which
            # made cycling-but-failing businesses look inactive to fitness).
            record = SkillCallRecord(
                skill_name=name, caller_id=ctx.caller_id, params=params,
                result=None, cost_usd=0.0, latency_ms=0, ok=False,
                error=f"unknown skill: {name}",
            )
            self._record_live_call(name, False)
            await self._record_db_stat(record, business_id=ctx.business_id)
            return record

        # Identify which META params lack a default in the run() signature.
        # Params with defaults in run() are optional even if listed in META.
        sig = inspect.signature(skill.run)
        required_params = {
            pname
            for pname, param in sig.parameters.items()
            if pname != "ctx"
            and param.default is inspect.Parameter.empty
            and param.kind not in (
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            )
        }
        missing = [p for p in required_params if p not in params]
        if missing:
            record = SkillCallRecord(
                skill_name=name, caller_id=ctx.caller_id, params=params,
                result=None, cost_usd=0.0, latency_ms=0, ok=False,
                error=f"missing required param: {missing[0]}",
            )
            self._record_live_call(name, False)
            await self._record_db_stat(record, business_id=ctx.business_id)
            return record

        # Z5b: strip extra kwargs not in the skill's run() signature.
        # LLMs routinely add extra fields (filter, hints, context) to action
        # JSON that the skill doesn't accept — causing TypeError and canary
        # demotion of perfectly good skills. Skills with **kwargs in run()
        # are exempt; we pass them everything.
        sig_params = sig.parameters
        has_var_kw = any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in sig_params.values()
        )
        if not has_var_kw:
            known = {pname for pname in sig_params if pname != "ctx"}
            params = {k: v for k, v in params.items() if k in known}

        start = time.monotonic()
        record: SkillCallRecord
        try:
            result = await asyncio.wait_for(
                skill.run(ctx, **params),
                timeout=skill.meta.timeout_s,
            )
            elapsed_ms = int((time.monotonic() - start) * 1000)
            if not isinstance(result, dict):
                record = SkillCallRecord(
                    skill_name=name,
                    caller_id=ctx.caller_id,
                    params=params,
                    result=None,
                    cost_usd=0.0,
                    latency_ms=elapsed_ms,
                    ok=False,
                    error=f"skill returned non-dict: {type(result).__name__}",
                )
            else:
                missing_fields = [f for f in skill.meta.returns if f not in result]
                if missing_fields:
                    record = SkillCallRecord(
                        skill_name=name,
                        caller_id=ctx.caller_id,
                        params=params,
                        result=None,
                        cost_usd=0.0,
                        latency_ms=elapsed_ms,
                        ok=False,
                        error=f"missing return field: {missing_fields[0]}",
                    )
                # Z3.5: skills that silently degrade by returning {"ok": False, ...}
                # were being recorded as ok=true (because they didn't raise and
                # returned a dict with all META fields). The substrate then
                # marked the cycle as an artifact and reset stall, hallucinating
                # progress. Honor the inner `ok` field as authoritative when
                # the skill declares it in META.returns.
                elif "ok" in result and result.get("ok") is False:
                    record = SkillCallRecord(
                        skill_name=name,
                        caller_id=ctx.caller_id,
                        params=params,
                        result=result,
                        cost_usd=0.0,
                        latency_ms=elapsed_ms,
                        ok=False,
                        error=str(result.get("error") or result.get("reason")
                                  or "skill returned ok=False (silent degradation)"),
                    )
                else:
                    record = SkillCallRecord(
                        skill_name=name,
                        caller_id=ctx.caller_id,
                        params=params,
                        result=result,
                        cost_usd=skill.meta.cost_estimate_usd,
                        latency_ms=elapsed_ms,
                        ok=True,
                        error=None,
                    )
        except asyncio.TimeoutError:
            record = SkillCallRecord(
                skill_name=name,
                caller_id=ctx.caller_id,
                params=params,
                result=None,
                cost_usd=0.0,
                latency_ms=int((time.monotonic() - start) * 1000),
                ok=False,
                error=f"timeout after {skill.meta.timeout_s}s",
            )
        except Exception as exc:
            record = SkillCallRecord(
                skill_name=name,
                caller_id=ctx.caller_id,
                params=params,
                result=None,
                cost_usd=0.0,
                latency_ms=int((time.monotonic() - start) * 1000),
                ok=False,
                error=f"{type(exc).__name__}: {exc}",
            )
        self._record_live_call(name, record.ok)
        await self._record_db_stat(record, business_id=ctx.business_id)
        return record

    async def run_watcher(self) -> None:
        """Poll skills_dir for changes; reload on add/modify/delete. Runs forever."""
        seen: dict[Path, float] = {
            p: p.stat().st_mtime for p in self._dir.rglob("*.py") if p.is_file()
        }
        while True:
            await asyncio.sleep(1.0)
            try:
                current = {
                    p: p.stat().st_mtime for p in self._dir.rglob("*.py") if p.is_file()
                }
            except FileNotFoundError:
                continue

            # New or modified files
            for path, mtime in current.items():
                if seen.get(path) != mtime:
                    try:
                        self._load_one(path)
                    except SkillValidationError as exc:
                        logger.warning("hot-reload rejected: %s — %s", path, exc)
                    except Exception as exc:
                        logger.error("hot-reload error: %s — %s", path, exc)

            # Deleted files — drop from registry
            for path in seen.keys() - current.keys():
                for name, loaded in list(self._skills.items()):
                    if loaded.source_path == path:
                        del self._skills[name]
                        logger.info("skill removed (file deleted): %s", name)

            seen = current


# Module-level singleton — initialised in main.py startup, consumed by DirectiveRouter.
REGISTRY: SkillRegistry | None = None


def init_skill_system(skills_dir: Path) -> SkillRegistry:
    global REGISTRY
    REGISTRY = SkillRegistry(skills_dir=skills_dir)
    REGISTRY.discover()
    return REGISTRY
