"""Renders the skill catalog into a prompt block, filtered by executive role.

The default role-mapping below is a starting point. Skills whose META carries
a `roles` key override the default; skills with empty `roles` are universal.
The CEO always sees the union — the org's most senior agent must reason about
the full action surface."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SkillCatalogEntry:
    name: str
    description: str
    params: dict[str, str]
    roles: list[str]


# Default role visibility for builtin skill prefixes. Skills not matching any
# prefix default to universal (visible to all roles). Skills with explicit
# `roles` in META override this.
_PREFIX_DEFAULTS: dict[str, list[str]] = {
    "stripe_": ["cfo", "ceo"],
    "account_": ["cmo", "cto", "ceo"],
    "x_post": ["cmo", "ceo"],
    "linkedin_": ["cmo", "ceo"],
    "reddit_": ["cmo", "ceo"],
    "email_": ["cmo", "cfo", "ceo"],
    "fs_": ["cto", "ceo"],
    "vector_": ["cto", "ceo"],
    "llm_": ["cto", "cmo", "ceo"],
    "browser_": ["cmo", "cto", "ceo"],
    "sql_": ["cfo", "cto", "ceo"],
    "operator_": ["ceo", "cfo", "cmo", "coo", "cto"],  # everyone can escalate
    "worker_": ["ceo"],  # only CEO hires/fires
    "skill_request": ["cto", "ceo"],
}


def _effective_roles(entry: SkillCatalogEntry) -> list[str]:
    if entry.roles:
        return entry.roles
    for prefix, roles in _PREFIX_DEFAULTS.items():
        if entry.name.startswith(prefix):
            return roles
    return []  # empty list = universal


def render_for_role(role: str, entries: list[SkillCatalogEntry]) -> str:
    """Render a prompt-friendly catalog block for the given role.

    Format:
        Available skills (output as JSON {"action": "<skill_name>", ...params}):
        - skill_name(param1: type, param2: type) — description
        - ...
    """
    if not entries:
        return "Available skills: (no skills currently registered)"

    visible = sorted(
        [e for e in entries if not _effective_roles(e) or role in _effective_roles(e) or role == "ceo"],
        key=lambda e: e.name,
    )
    if not visible:
        return f"Available skills for {role}: (none)"

    lines = ['Available skills (invoke via {"action": "<skill_name>", ...params}):']
    for e in visible:
        if e.params:
            sig = ", ".join(f"{k}: {v}" for k, v in e.params.items())
            lines.append(f'- {e.name}({sig}) — {e.description}')
        else:
            lines.append(f"- {e.name}() — {e.description}")
    return "\n".join(lines)
