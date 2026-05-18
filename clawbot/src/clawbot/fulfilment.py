"""
Z3 — fulfilment template loader + render.

Each genome names a `fulfilment_template` (e.g. "ir35_quickcheck_v1"). The
template lives at `agents/fulfilment_templates/<name>.md` and consists of:
- YAML frontmatter with `required_inputs` list and `ai_disclosure` string
- Markdown body with `{{ var }}` placeholders rendered against the
  customer's quiz inputs

This module loads + validates templates, renders the LLM prompt, and
exposes a small API the `deliver_personalised_report` skill consumes.

Templates are content, not code — operator can edit a template (or the
agent can author a new one via skill_request) without touching Python.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import re


_TEMPLATES_DIR = (
    Path(__file__).parent.parent.parent / "agents" / "fulfilment_templates"
)


class FulfilmentTemplateError(ValueError):
    """Raised when a template is missing, malformed, or missing required inputs."""


@dataclass(frozen=True)
class FulfilmentTemplate:
    name: str
    description: str
    required_inputs: list[str]
    ai_disclosure: str
    prompt_body: str

    def render_prompt(self, inputs: dict[str, Any]) -> str:
        """Substitute `{{ var }}` placeholders with input values.

        Raises FulfilmentTemplateError if a required input is missing.
        Missing optional vars render as `(not provided)` so the LLM has
        something to reason about.
        """
        missing = [k for k in self.required_inputs if not inputs.get(k)]
        if missing:
            raise FulfilmentTemplateError(
                f"template {self.name} missing required inputs: {missing}"
            )
        out = self.prompt_body
        for key, value in inputs.items():
            out = out.replace("{{ " + key + " }}", str(value))
        # Replace any remaining {{ var }} with "(not provided)" so the LLM
        # doesn't see literal placeholders if the customer left blanks.
        out = re.sub(r"\{\{\s*\w+\s*\}\}", "(not provided)", out)
        return out


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse YAML-ish frontmatter (between leading `---` lines). Returns
    (metadata_dict, body_str). We use a stdlib-only parser since the
    expected schema is shallow (top-level strings + a single list)."""
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    front_raw = text[4:end]
    body = text[end + 5:]
    meta: dict[str, Any] = {}
    current_list_key: str | None = None
    current_list: list[str] = []
    for line in front_raw.split("\n"):
        if not line.strip():
            continue
        if line.startswith("  - ") and current_list_key:
            current_list.append(line[4:].strip())
            continue
        # Flush any pending list
        if current_list_key:
            meta[current_list_key] = current_list
            current_list_key = None
            current_list = []
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        if not val:
            current_list_key = key
            current_list = []
        else:
            meta[key] = val
    if current_list_key:
        meta[current_list_key] = current_list
    return meta, body


def load_template(
    name: str, *, templates_dir: Path | None = None,
) -> FulfilmentTemplate:
    """Load + validate a fulfilment template by name (no `.md` suffix)."""
    base = templates_dir or _TEMPLATES_DIR
    path = base / f"{name}.md"
    if not path.exists():
        raise FulfilmentTemplateError(f"template not found: {name} (looked in {base})")
    text = path.read_text(encoding="utf-8")
    meta, body = _split_frontmatter(text)
    required = meta.get("required_inputs") or []
    if not isinstance(required, list):
        raise FulfilmentTemplateError(
            f"template {name}: required_inputs must be a list, got {type(required).__name__}"
        )
    disclosure = str(meta.get("ai_disclosure") or "").strip()
    if not disclosure:
        raise FulfilmentTemplateError(
            f"template {name}: ai_disclosure is required (charter compliance)"
        )
    return FulfilmentTemplate(
        name=str(meta.get("name") or name),
        description=str(meta.get("description") or ""),
        required_inputs=[str(r) for r in required],
        ai_disclosure=disclosure,
        prompt_body=body.strip(),
    )


def list_templates(*, templates_dir: Path | None = None) -> list[str]:
    """Return names of all available templates (filename stem)."""
    base = templates_dir or _TEMPLATES_DIR
    if not base.exists():
        return []
    return sorted(p.stem for p in base.glob("*.md"))
