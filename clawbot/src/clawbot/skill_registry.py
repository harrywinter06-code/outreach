"""In-memory skill registry: discover from disk, validate, call by name.

Discovery is one-shot at startup; hot-reload is added in Task 5.
"""
from __future__ import annotations

import asyncio
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


class SkillRegistry:
    def __init__(self, skills_dir: Path) -> None:
        self._dir = skills_dir
        self._skills: dict[str, _LoadedSkill] = {}

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

    def list_names(self) -> list[str]:
        return sorted(self._skills.keys())

    def get_meta(self, name: str) -> SkillMeta | None:
        skill = self._skills.get(name)
        return skill.meta if skill else None

    async def call(
        self,
        name: str,
        params: dict[str, Any],
        ctx: SkillCtx,
    ) -> SkillCallRecord:
        skill = self._skills.get(name)
        if skill is None:
            return SkillCallRecord(
                skill_name=name,
                caller_id=ctx.caller_id,
                params=params,
                result=None,
                cost_usd=0.0,
                latency_ms=0,
                ok=False,
                error=f"unknown skill: {name}",
            )

        missing = [p for p in skill.meta.params if p not in params]
        if missing:
            return SkillCallRecord(
                skill_name=name,
                caller_id=ctx.caller_id,
                params=params,
                result=None,
                cost_usd=0.0,
                latency_ms=0,
                ok=False,
                error=f"missing required param: {missing[0]}",
            )

        start = time.monotonic()
        try:
            result = await asyncio.wait_for(
                skill.run(ctx, **params),
                timeout=skill.meta.timeout_s,
            )
            elapsed_ms = int((time.monotonic() - start) * 1000)
            if not isinstance(result, dict):
                return SkillCallRecord(
                    skill_name=name,
                    caller_id=ctx.caller_id,
                    params=params,
                    result=None,
                    cost_usd=0.0,
                    latency_ms=elapsed_ms,
                    ok=False,
                    error=f"skill returned non-dict: {type(result).__name__}",
                )
            return SkillCallRecord(
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
            return SkillCallRecord(
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
            return SkillCallRecord(
                skill_name=name,
                caller_id=ctx.caller_id,
                params=params,
                result=None,
                cost_usd=0.0,
                latency_ms=int((time.monotonic() - start) * 1000),
                ok=False,
                error=f"{type(exc).__name__}: {exc}",
            )

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
