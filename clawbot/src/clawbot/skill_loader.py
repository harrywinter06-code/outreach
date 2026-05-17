"""AST allowlist scanner + restricted-builtins loader for organism-authored skills.

A skill that imports `os` and shells out defeats every other safety mechanism in
the system. This module is the load-time check that prevents that.

Allowed imports: stdlib pure-data modules only (json, re, math, datetime,
hashlib, base64, dataclasses, typing, collections, itertools, functools).
Everything else — including httpx, requests, asyncio.subprocess, socket — is
rejected. Skills do I/O through `ctx`, never directly.
"""
from __future__ import annotations

import ast
from typing import Iterable

FORBIDDEN_CALLS: frozenset[str] = frozenset({
    "eval", "exec", "compile", "__import__", "open",
    "getattr", "setattr", "delattr", "globals", "locals", "vars",
    "input", "breakpoint",
})

ALLOWED_IMPORTS: frozenset[str] = frozenset({
    "json", "re", "math", "datetime", "hashlib", "base64", "uuid",
    "dataclasses", "typing", "collections", "itertools", "functools",
    "decimal", "fractions", "string", "textwrap",
})


class SkillValidationError(ValueError):
    """Raised when skill source fails the AST allowlist scan."""


def _walk_imports(tree: ast.AST) -> Iterable[str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                yield node.module.split(".")[0]


def _has_meta_and_run(tree: ast.AST) -> tuple[bool, ast.AsyncFunctionDef | None]:
    has_meta = False
    run_fn: ast.AsyncFunctionDef | None = None
    for node in tree.body:  # type: ignore[attr-defined]
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "META":
                    has_meta = True
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "run":
            run_fn = node
    return has_meta, run_fn


def scan_skill_source(source: str) -> None:
    """Raise SkillValidationError if source is not safe to load as a skill."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise SkillValidationError(f"syntax error: {exc}") from exc

    for mod in _walk_imports(tree):
        if mod not in ALLOWED_IMPORTS:
            raise SkillValidationError(f"forbidden import: {mod}")

    has_meta, run_fn = _has_meta_and_run(tree)
    if not has_meta:
        raise SkillValidationError("skill must define META dict at module level")
    if run_fn is None:
        raise SkillValidationError("skill must define `async def run(ctx, ...)` at module level")
    if not run_fn.args.args or run_fn.args.args[0].arg != "ctx":
        raise SkillValidationError("run must be async and take ctx as first arg")

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in FORBIDDEN_CALLS:
                raise SkillValidationError(f"forbidden call: {node.func.id}")
        if isinstance(node, ast.Attribute):
            if node.attr.startswith("__") and node.attr.endswith("__"):
                raise SkillValidationError(f"dunder attribute access: {node.attr}")


def load_skill_module(source: str, module_name: str) -> dict:
    """Compile source with restricted builtins, return its module namespace.

    Caller MUST scan first via scan_skill_source. This function does not re-scan —
    re-scanning here would mask bugs in the scanner.
    """
    raw = __builtins__ if isinstance(__builtins__, dict) else vars(__builtins__)
    safe_builtins: dict = {}
    for name in (
        "abs", "all", "any", "bool", "bytes", "callable", "chr", "dict",
        "divmod", "enumerate", "filter", "float", "format", "frozenset",
        "hash", "hex", "id", "int", "isinstance", "issubclass", "iter",
        "len", "list", "map", "max", "min", "next", "oct", "ord", "pow",
        "print", "range", "repr", "reversed", "round", "set", "slice",
        "sorted", "str", "sum", "tuple", "type", "zip",
        "Exception", "ValueError", "TypeError", "RuntimeError",
        "KeyError", "IndexError", "AttributeError",
    ):
        if name in raw:
            safe_builtins[name] = raw[name]

    namespace: dict = {"__builtins__": safe_builtins, "__name__": module_name}
    code = compile(source, f"<skill:{module_name}>", "exec")
    exec(code, namespace)  # noqa: S102 — restricted builtins, AST-scanned source
    return namespace
