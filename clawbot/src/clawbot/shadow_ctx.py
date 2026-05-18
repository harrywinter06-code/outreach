"""Shadow-mode SkillCtx: fixture-backed HTTP, tmpfs fs, no-op everything else.

The point of shadow mode is to catch shape mismatches: an LLM-authored skill
that parses `r["data"]["id"]` against Stripe (which returns `r["id"]` at top
level) errors at shadow time, never reaches live.
"""
from __future__ import annotations

import json as _json
import tempfile
from pathlib import Path
from typing import Any

from clawbot.skill_ctx import (
    SkillCtx,
    _NoopAccounts,
    _NoopBrowser,
    _NoopBus,
    _NoopDev,
    _NoopEmail,
    _NoopLlm,
    _NoopLog,
    _NoopOperator,
    _NoopPayments,
    _NoopSearch,
    _NoopSecret,
    _NoopSocial,
    _NoopSql,
    _NoopTime,
    _NoopVector,
)
from clawbot.shadow_fixtures import lookup_fixture


class _ShadowHttp:
    async def get(self, url: str, *, headers: dict[str, str] | None = None) -> dict[str, Any]:
        f = lookup_fixture("GET", url)
        if f is None:
            return {"status": 200, "text": "", "headers": {}}
        return {
            "status": f["status"],
            "text": _json.dumps(f["json"]),
            "headers": f.get("headers", {}),
        }

    async def post(
        self,
        url: str,
        *,
        json: dict | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        # Use _json alias to avoid shadowing the `json` parameter name
        f = lookup_fixture("POST", url)
        if f is None:
            return {"status": 200, "text": "", "headers": {}}
        return {
            "status": f["status"],
            "text": _json.dumps(f["json"]),
            "headers": f.get("headers", {}),
        }


class _ShadowFs:
    """Writes go to a per-run tmpdir; reads return empty unless previously written."""

    def __init__(self) -> None:
        self._tmpdir = Path(tempfile.mkdtemp(prefix="shadow_fs_"))

    async def read(self, path: str) -> str:
        p = self._tmpdir / Path(path).name
        return p.read_text(encoding="utf-8") if p.exists() else ""

    async def write(self, path: str, content: str) -> None:
        p = self._tmpdir / Path(path).name
        p.write_text(content, encoding="utf-8")

    async def list(self, path: str) -> list[str]:
        return [str(p) for p in self._tmpdir.iterdir()]


def make_shadow_ctx(*, caller_id: str, budget_usd: float) -> SkillCtx:
    """Return a SkillCtx suitable for shadow-mode validation runs.

    HTTP is fixture-backed (catches API-shape hallucinations), fs uses a
    tmpdir, all other clients are no-ops.
    """
    return SkillCtx(
        http=_ShadowHttp(),
        sql=_NoopSql(),
        llm=_NoopLlm(),
        vector=_NoopVector(),
        secret=_NoopSecret(),
        fs=_ShadowFs(),
        time=_NoopTime(),
        operator=_NoopOperator(),
        bus=_NoopBus(),
        log=_NoopLog(),
        browser=_NoopBrowser(),
        payments=_NoopPayments(),
        social=_NoopSocial(),
        email=_NoopEmail(),
        search=_NoopSearch(),
        accounts=_NoopAccounts(),
        dev=_NoopDev(),
        caller_id=caller_id,
        budget_usd=budget_usd,
    )
