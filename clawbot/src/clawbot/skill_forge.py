"""Authorship loop: consume skill.request, draft via LLM, AST-validate, shadow, promote.

Shadow mode uses a SkillCtx with no-op HTTP/operator/fs but real LLM (capped to
$0.05 per shadow run via budget). If the skill returns a dict matching the
declared returns_schema shape across N=3 invocations, it is promoted to live.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

from clawbot.skill_ctx import make_noop_ctx
from clawbot.skill_loader import scan_skill_source, SkillValidationError
from clawbot.skill_registry import SkillRegistry

logger = logging.getLogger(__name__)

SHADOW_ITERATIONS = 3
SHADOW_BUDGET_USD = 0.05

_FORGE_PROMPT = """\
You are the skill-author for an autonomous AI company. Produce a Python module
that defines exactly one new skill following the contract below.

Skill name: {name}
Description: {description}
Params schema (param_name → type): {params_schema}
Returns schema (field → type): {returns_schema}
Example call: {example_call}
Requested by agent: {requested_by}

CONTRACT:
- Module defines exactly: `META` dict and `async def run(ctx, ...)` taking the params named above
- META: {{"name": "{name}", "description": "...", "params": {{...}}, "returns": {{...}}}}
- Only these imports allowed (stdlib pure-data only):
  json, re, math, datetime, hashlib, base64, uuid, dataclasses, typing, collections,
  itertools, functools, decimal, fractions, string, textwrap
- ALL I/O goes through ctx: ctx.http, ctx.sql, ctx.llm, ctx.vector, ctx.secret,
  ctx.fs, ctx.time, ctx.operator, ctx.bus, ctx.log
- NO direct imports of: os, sys, subprocess, socket, httpx, requests, asyncio, threading
- NO dynamic attribute access, eval, exec, compile, __import__, getattr with non-literal
- run MUST be `async def`, MUST return a dict matching returns schema

Output ONLY the file contents. No markdown fences. No explanation.
"""


class SkillForge:
    def __init__(
        self,
        llm_pool: Any,
        bus: Any,
        registry: SkillRegistry,
        skills_dir: Path,
        archive_dir: Path,
        brain: Any,
        db_pool: Any,
        escalation: Any,
    ) -> None:
        self._pool = llm_pool
        self._bus = bus
        self._registry = registry
        self._skills_dir = skills_dir
        self._archive = archive_dir
        self._brain = brain
        self._db_pool = db_pool
        self._escalation = escalation

    async def run_loop(self) -> None:
        await self._bus.subscribe("skill.request")
        while True:
            msgs = await self._bus.read_and_ack(
                "skill.request", "skill-forge", count=1, block_ms=10_000,
            )
            for m in msgs:
                try:
                    await self._handle_request(m)
                except Exception as exc:
                    logger.error("forge error: %s", exc)

    async def _handle_request(self, req: dict) -> None:
        name = req["name"]
        if self._registry.get_meta(name) is not None:
            await self._publish_result(False, name, "skill name already exists")
            return

        prompt = _FORGE_PROMPT.format(
            name=name,
            description=req["description"],
            params_schema=req.get("params_schema", {}),
            returns_schema=req.get("returns_schema", {}),
            example_call=req.get("example_call", {}),
            requested_by=req.get("requested_by", "unknown"),
        )
        messages = [
            {"role": "system", "content": "You author skills following an exact contract."},
            {"role": "user", "content": prompt},
        ]
        draft = await self._pool.complete(messages, tier="executive")
        draft = _strip_fences(draft)

        try:
            scan_skill_source(draft)
        except SkillValidationError as exc:
            await self._archive_failure(name, draft, f"ast_scan: {exc}")
            await self._publish_result(False, name, f"ast_scan: {exc}")
            return

        # Shadow execution: load into a temp registry, run example_call N times.
        shadow_path = self._archive / f"{name}-{int(time.time())}.candidate.py"
        shadow_path.write_text(draft, encoding="utf-8")
        shadow_reg = SkillRegistry(skills_dir=self._archive)
        shadow_reg.discover()
        if name not in shadow_reg.list_names():
            await self._publish_result(False, name, "candidate failed to load post-archive")
            return

        example = req.get("example_call", {})
        ctx = make_noop_ctx(caller_id=f"shadow-{name}", budget_usd=SHADOW_BUDGET_USD)
        for i in range(SHADOW_ITERATIONS):
            rec = await shadow_reg.call(name, example, ctx)
            if not rec.ok:
                await self._archive_failure(name, draft, f"shadow_iter_{i}: {rec.error}")
                await self._publish_result(False, name, f"shadow_iter_{i}: {rec.error}")
                return
            returns_schema = req.get("returns_schema", {})
            missing_fields = [f for f in returns_schema if f not in (rec.result or {})]
            if missing_fields:
                await self._archive_failure(name, draft, f"shadow_iter_{i}: missing returns {missing_fields}")
                await self._publish_result(False, name, f"shadow returns missing: {missing_fields}")
                return

        # Promote: copy from archive to live skills dir
        live_path = self._skills_dir / f"{name}.py"
        live_path.write_text(draft, encoding="utf-8")
        self._registry.discover()  # pick up the new skill
        logger.info("skill promoted: %s", name)
        await self._publish_result(True, name, "promoted")

    async def _archive_failure(self, name: str, draft: str, reason: str) -> None:
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        path = self._archive / f"{name}-{ts}.failed.py"
        path.write_text(f"# REJECTED: {reason}\n# Drafted at {ts}\n\n{draft}", encoding="utf-8")
        logger.warning("skill rejected: %s — %s", name, reason)

    async def _publish_result(self, ok: bool, name: str, detail: str) -> None:
        try:
            await self._bus.publish("skill.result", {
                "name": name, "ok": ok, "detail": detail,
                "at": datetime.now(UTC).isoformat(),
            })
        except Exception:
            pass


def _strip_fences(text: str) -> str:
    """Strip ```python / ``` fences that LLMs add despite being told not to."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return text
