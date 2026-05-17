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
