"""Z3 — fulfilment template loader + render tests."""
from pathlib import Path

import pytest


def _write_template(tmp_path: Path, name: str, content: str) -> Path:
    d = tmp_path / "templates"
    d.mkdir(exist_ok=True)
    p = d / f"{name}.md"
    p.write_text(content, encoding="utf-8")
    return d


def test_load_template_parses_frontmatter_and_body(tmp_path):
    from clawbot.fulfilment import load_template
    d = _write_template(tmp_path, "test_v1", """---
name: test_v1
description: A test template
required_inputs:
  - role
  - tenure
ai_disclosure: This is AI-generated, not advice.
---
Hello {{ role }} of tenure {{ tenure }}.""")
    t = load_template("test_v1", templates_dir=d)
    assert t.name == "test_v1"
    assert t.description == "A test template"
    assert t.required_inputs == ["role", "tenure"]
    assert "AI-generated" in t.ai_disclosure
    assert "Hello {{ role }}" in t.prompt_body


def test_render_substitutes_all_placeholders(tmp_path):
    from clawbot.fulfilment import load_template
    d = _write_template(tmp_path, "t2", """---
name: t2
required_inputs:
  - a
  - b
ai_disclosure: x
---
A={{ a }} B={{ b }}""")
    t = load_template("t2", templates_dir=d)
    out = t.render_prompt({"a": "alpha", "b": "beta"})
    assert "A=alpha B=beta" in out


def test_render_raises_when_required_input_missing(tmp_path):
    from clawbot.fulfilment import load_template, FulfilmentTemplateError
    d = _write_template(tmp_path, "t3", """---
name: t3
required_inputs:
  - must_have
ai_disclosure: x
---
{{ must_have }}""")
    t = load_template("t3", templates_dir=d)
    with pytest.raises(FulfilmentTemplateError, match="missing required inputs"):
        t.render_prompt({})


def test_render_replaces_extra_placeholders_with_not_provided(tmp_path):
    """Optional placeholders the customer didn't fill should not leak as
    literal `{{ var }}` into the LLM prompt."""
    from clawbot.fulfilment import load_template
    d = _write_template(tmp_path, "t4", """---
name: t4
required_inputs:
  - r
ai_disclosure: x
---
{{ r }} and {{ optional }}""")
    t = load_template("t4", templates_dir=d)
    out = t.render_prompt({"r": "yes"})
    assert "{{ optional }}" not in out
    assert "(not provided)" in out


def test_load_template_raises_when_missing_ai_disclosure(tmp_path):
    """Charter compliance: every fulfilment template must declare its
    AI-disclosure string. Without it, the customer email wouldn't carry
    the legally-required disclosure."""
    from clawbot.fulfilment import load_template, FulfilmentTemplateError
    d = _write_template(tmp_path, "t5", """---
name: t5
required_inputs:
  - foo
---
body""")
    with pytest.raises(FulfilmentTemplateError, match="ai_disclosure"):
        load_template("t5", templates_dir=d)


def test_load_template_raises_on_missing_file(tmp_path):
    from clawbot.fulfilment import load_template, FulfilmentTemplateError
    d = tmp_path / "empty"
    d.mkdir()
    with pytest.raises(FulfilmentTemplateError, match="not found"):
        load_template("nope", templates_dir=d)


def test_ir35_template_loads_from_real_path():
    """The shipped IR35 template must be loadable + have the inputs the
    lander form generates fields for."""
    from clawbot.fulfilment import load_template
    t = load_template("ir35_quickcheck_v1")
    assert t.name == "ir35_quickcheck_v1"
    assert "role_summary" in t.required_inputs
    assert "substitution_right" in t.required_inputs
    assert "AI-generated" in t.ai_disclosure


def test_list_templates_includes_shipped_ir35():
    from clawbot.fulfilment import list_templates
    names = list_templates()
    assert "ir35_quickcheck_v1" in names
