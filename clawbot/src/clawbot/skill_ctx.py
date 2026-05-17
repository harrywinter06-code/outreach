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
