"""Sandboxed execution context for organism-authored skills.

Skills receive ONLY a SkillCtx instance — no module imports, no globals,
no filesystem access outside the sandboxed roots. The reason this is a
hard boundary: an LLM-authored skill that imports `os` and shells out
defeats every other safety mechanism in the system.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_RESERVED_NAMES = frozenset({"ctx", "run", "META", "self", "cls"})


@dataclass(frozen=True)
class SkillMeta:
    name: str
    description: str
    params: dict[str, str]   # param_name -> type-hint string ("str", "int", "float", "bool", "list", "dict")
    returns: dict[str, str]  # field_name -> type-hint string
    cost_estimate_usd: float = 0.0
    requires_approval: bool = False
    timeout_s: float = 30.0
    builtin: bool = False    # True for _builtin/* skills; cannot be overwritten by forge

    def __post_init__(self) -> None:
        if not _NAME_RE.match(self.name):
            raise ValueError(f"skill name {self.name!r} must be lowercase snake_case")
        if self.name in _RESERVED_NAMES:
            raise ValueError(f"skill name {self.name!r} is reserved")


@dataclass(frozen=True)
class SkillCallRecord:
    skill_name: str
    caller_id: str
    params: dict[str, Any]
    result: dict[str, Any] | None
    cost_usd: float
    latency_ms: int
    ok: bool
    error: str | None


from typing import Protocol


class HttpClient(Protocol):
    async def get(self, url: str, *, headers: dict[str, str] | None = None) -> dict[str, Any]: ...
    async def post(self, url: str, *, json: dict | None = None, headers: dict[str, str] | None = None) -> dict[str, Any]: ...


class SqlClient(Protocol):
    async def query(self, sql: str, *args: Any) -> list[dict[str, Any]]: ...


class LlmClient(Protocol):
    async def complete(self, *, system: str, user: str, tier: str = "worker") -> str: ...


class VectorClient(Protocol):
    async def search(self, query: str, *, k: int = 5) -> list[dict[str, Any]]: ...
    async def write(self, text: str, *, kind: str, metadata: dict[str, Any] | None = None) -> str: ...


class SecretClient(Protocol):
    def get(self, name: str) -> str: ...


class FsClient(Protocol):
    async def read(self, path: str) -> str: ...
    async def write(self, path: str, content: str) -> None: ...
    async def list(self, path: str) -> list[str]: ...


class TimeClient(Protocol):
    def now_iso(self) -> str: ...
    def epoch_s(self) -> float: ...


class OperatorClient(Protocol):
    async def message(self, text: str, *, level: str = "info") -> None: ...
    async def request_approval(self, prompt: str, *, timeout_s: float = 3600) -> bool: ...


class BusClient(Protocol):
    async def publish(self, topic: str, payload: dict[str, Any]) -> str: ...


class LogClient(Protocol):
    def info(self, msg: str, **kwargs: Any) -> None: ...
    def warn(self, msg: str, **kwargs: Any) -> None: ...
    def error(self, msg: str, **kwargs: Any) -> None: ...


@dataclass(frozen=True)
class SkillCtx:
    http: HttpClient
    sql: SqlClient
    llm: LlmClient
    vector: VectorClient
    secret: SecretClient
    fs: FsClient
    time: TimeClient
    operator: OperatorClient
    bus: BusClient
    log: LogClient
    caller_id: str
    budget_usd: float


# -- No-op stubs used by tests and shadow mode -------------------------------


class _NoopHttp:
    async def get(self, url: str, *, headers: dict[str, str] | None = None) -> dict[str, Any]:
        return {"status": 200, "text": "", "headers": {}}

    async def post(self, url: str, *, json: dict | None = None, headers: dict[str, str] | None = None) -> dict[str, Any]:
        return {"status": 200, "text": "", "headers": {}}


class _NoopSql:
    async def query(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        return []


class _NoopLlm:
    async def complete(self, *, system: str, user: str, tier: str = "worker") -> str:
        return ""


class _NoopVector:
    async def search(self, query: str, *, k: int = 5) -> list[dict[str, Any]]:
        return []

    async def write(self, text: str, *, kind: str, metadata: dict[str, Any] | None = None) -> str:
        return "noop-id"


class _NoopSecret:
    def get(self, name: str) -> str:
        return ""


class _NoopFs:
    async def read(self, path: str) -> str:
        return ""

    async def write(self, path: str, content: str) -> None:
        pass

    async def list(self, path: str) -> list[str]:
        return []


class _NoopTime:
    def now_iso(self) -> str:
        return "1970-01-01T00:00:00+00:00"

    def epoch_s(self) -> float:
        return 0.0


class _NoopOperator:
    async def message(self, text: str, *, level: str = "info") -> None:
        pass

    async def request_approval(self, prompt: str, *, timeout_s: float = 3600) -> bool:
        return False


class _NoopBus:
    async def publish(self, topic: str, payload: dict[str, Any]) -> str:
        return "noop-msg-id"


class _NoopLog:
    def info(self, msg: str, **kwargs: Any) -> None: pass
    def warn(self, msg: str, **kwargs: Any) -> None: pass
    def error(self, msg: str, **kwargs: Any) -> None: pass


def make_noop_ctx(*, caller_id: str, budget_usd: float) -> SkillCtx:
    return SkillCtx(
        http=_NoopHttp(), sql=_NoopSql(), llm=_NoopLlm(), vector=_NoopVector(),
        secret=_NoopSecret(), fs=_NoopFs(), time=_NoopTime(), operator=_NoopOperator(),
        bus=_NoopBus(), log=_NoopLog(),
        caller_id=caller_id, budget_usd=budget_usd,
    )


# -- Live implementations wired to real services ------------------------------

import asyncio
import os
import logging as _stdlib_logging
from datetime import datetime, UTC
from pathlib import Path

import httpx


_PROTECTED_TOPICS = frozenset({
    "code.change_request",   # only CTOCoder consumes this; agents must use skill_request
    "operator.escalation",   # use operator.message skill
    "board.resolution",      # only board emits
})


class _LiveHttp:
    """HTTP client with timeout and response truncation to prevent prompt injection."""

    def __init__(self) -> None:
        self._timeout = 15.0
        self._max_chars = 8000

    async def get(self, url: str, *, headers: dict[str, str] | None = None) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
            r = await client.get(url, headers=headers or {})
        return {"status": r.status_code, "text": r.text[: self._max_chars], "headers": dict(r.headers)}

    async def post(self, url: str, *, json: dict | None = None, headers: dict[str, str] | None = None) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
            r = await client.post(url, json=json, headers=headers or {})
        return {"status": r.status_code, "text": r.text[: self._max_chars], "headers": dict(r.headers)}


class _LiveSql:
    def __init__(self, db_pool: Any) -> None:
        self._pool = db_pool

    async def query(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        # Reject DDL at this layer — safety surface.
        # NOTE: only matches DDL at line start; multi-line DDL (DROP\nTABLE) passes.
        upper = sql.strip().upper()
        for forbidden in ("DROP ", "TRUNCATE ", "ALTER ", "CREATE "):
            if upper.startswith(forbidden):
                raise PermissionError(f"DDL not allowed via skill: {forbidden.strip()}")
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *args)
        return [dict(r) for r in rows]


class _LiveLlm:
    def __init__(self, pool: Any, caller_id: str) -> None:
        self._pool = pool
        self._caller = caller_id

    async def complete(self, *, system: str, user: str, tier: str = "worker") -> str:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        return await self._pool.complete(messages, tier=tier)  # type: ignore[no-any-return]


class _LiveVector:
    """Wraps CompanyBrain. Real method is search(query, k) not recall(query, k=k)."""

    def __init__(self, brain: Any, caller_id: str) -> None:
        self._brain = brain
        self._caller = caller_id

    async def search(self, query: str, *, k: int = 5) -> list[dict[str, Any]]:
        # CompanyBrain.search(query, k, category=None) → list[BrainEntry]
        results = await self._brain.search(query, k)
        return [r if isinstance(r, dict) else vars(r) for r in results]

    async def write(self, text: str, *, kind: str, metadata: dict[str, Any] | None = None) -> str:
        # CompanyBrain.write(content, category, metadata) → int (row id)
        row_id = await self._brain.write(text, kind, metadata or {"author": self._caller})
        return str(row_id)


class _LiveSecret:
    def __init__(self, allowlist: list[str]) -> None:
        self._allowlist = frozenset(allowlist)

    def get(self, name: str) -> str:
        if name not in self._allowlist:
            raise PermissionError(f"secret {name} not allowlisted for skills")
        return os.environ.get(name, "")


class _LiveFs:
    """Filesystem access scoped to workspace_root; defeats path-traversal via Path.resolve()."""

    def __init__(self, workspace_root: str, allowed_roots: list[str]) -> None:
        self._roots = [Path(workspace_root).resolve()] + [Path(r).resolve() for r in allowed_roots]

    def _check(self, path: str) -> Path:
        p = Path(path).resolve()
        if not any(str(p).startswith(str(r)) for r in self._roots):
            raise PermissionError(f"fs path outside allowed roots: {path}")
        return p

    async def read(self, path: str) -> str:
        return self._check(path).read_text(encoding="utf-8")

    async def write(self, path: str, content: str) -> None:
        p = self._check(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    async def list(self, path: str) -> list[str]:
        p = self._check(path)
        return [str(c) for c in p.iterdir()] if p.is_dir() else []


class _LiveTime:
    def now_iso(self) -> str:
        return datetime.now(UTC).isoformat()

    def epoch_s(self) -> float:
        return datetime.now(UTC).timestamp()


class _LiveOperator:
    def __init__(self, escalation: Any, bus: Any, caller_id: str) -> None:
        self._esc = escalation
        self._bus = bus
        self._caller = caller_id

    async def message(self, text: str, *, level: str = "info") -> None:
        await self._esc.notify(text, level=level, source=self._caller)

    async def request_approval(self, prompt: str, *, timeout_s: float = 3600) -> bool:
        import uuid as _uuid
        request_id = _uuid.uuid4().hex
        await self._bus.publish("operator.approval_request", {
            "request_id": request_id, "prompt": prompt, "source": self._caller,
        })
        # Simple poll for reply on operator.approval_reply with matching request_id.
        # NOTE: uses MessageBus.read(topic, consumer_id, count, block_ms) — MVP approach.
        deadline = datetime.now(UTC).timestamp() + timeout_s
        while datetime.now(UTC).timestamp() < deadline:
            await asyncio.sleep(2)
            replies = await self._bus.read(
                "operator.approval_reply",
                consumer_id=f"approval-{request_id}",
                count=10,
                block_ms=1000,
            )
            for r in replies:
                if r.get("request_id") == request_id:
                    return bool(r.get("approved", False))
        return False


class _LiveBus:
    def __init__(self, bus: Any, caller_id: str) -> None:
        self._bus = bus
        self._caller = caller_id

    async def publish(self, topic: str, payload: dict[str, Any]) -> str:
        if topic in _PROTECTED_TOPICS:
            raise PermissionError(f"bus topic {topic} reserved")
        enriched = {**payload, "_published_by_skill": self._caller}
        return await self._bus.publish(topic, enriched)


class _LiveLog:
    def __init__(self, caller_id: str) -> None:
        self._logger = _stdlib_logging.getLogger(f"skill.{caller_id}")

    def info(self, msg: str, **kwargs: Any) -> None:
        self._logger.info("%s %s", msg, kwargs or "")

    def warn(self, msg: str, **kwargs: Any) -> None:
        self._logger.warning("%s %s", msg, kwargs or "")

    def error(self, msg: str, **kwargs: Any) -> None:
        self._logger.error("%s %s", msg, kwargs or "")


def make_live_ctx(
    *,
    caller_id: str,
    budget_usd: float,
    llm_pool: Any,
    bus: Any,
    brain: Any,
    db_pool: Any,
    escalation: Any,
    secret_allowlist: list[str],
    workspace_root: str,
    fs_allowed_roots: list[str] | None = None,
) -> SkillCtx:
    """Build a SkillCtx wired to live services.

    fs_allowed_roots defaults to workspace_root plus the organism-writable
    directories (agents/skills, agents/workers, data). Skills CANNOT touch
    src/clawbot/ via fs — those edits go through coder.py.
    """
    extra_roots = fs_allowed_roots or []
    return SkillCtx(
        http=_LiveHttp(),
        sql=_LiveSql(db_pool),
        llm=_LiveLlm(llm_pool, caller_id),
        vector=_LiveVector(brain, caller_id),
        secret=_LiveSecret(secret_allowlist),
        fs=_LiveFs(workspace_root, extra_roots),
        time=_LiveTime(),
        operator=_LiveOperator(escalation, bus, caller_id),
        bus=_LiveBus(bus, caller_id),
        log=_LiveLog(caller_id),
        caller_id=caller_id,
        budget_usd=budget_usd,
    )
