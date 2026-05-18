"""Tests for the skill catalog renderer -- role filtering + format."""
from clawbot.skill_catalog_renderer import render_for_role, SkillCatalogEntry


def _entry(name: str, description: str, params: dict, roles: list[str] | None = None) -> SkillCatalogEntry:
    return SkillCatalogEntry(name=name, description=description, params=params, roles=roles or [])


def test_renders_skill_block_with_name_description_params():
    entries = [
        _entry("fs_write", "Write a file to workspace", {"path": "str", "content": "str"}),
    ]
    out = render_for_role("cto", entries)
    assert "fs_write" in out
    assert "Write a file" in out
    assert "path" in out
    assert "content" in out


def test_filters_by_role_when_roles_declared():
    entries = [
        _entry("stripe_issue_card", "Issue card", {"daily_limit_usd": "int"}, roles=["cfo"]),
        _entry("x_post", "Post to X", {"text": "str"}, roles=["cmo"]),
    ]
    cfo_out = render_for_role("cfo", entries)
    cmo_out = render_for_role("cmo", entries)
    assert "stripe_issue_card" in cfo_out
    assert "x_post" not in cfo_out
    assert "x_post" in cmo_out
    assert "stripe_issue_card" not in cmo_out


def test_universal_skills_appear_for_every_role():
    entries = [_entry("time_now", "Get current time", {})]
    for role in ("ceo", "cfo", "cmo", "coo", "cto"):
        assert "time_now" in render_for_role(role, entries)


def test_ceo_sees_everything():
    entries = [
        _entry("stripe_issue_card", "Issue card", {}, roles=["cfo"]),
        _entry("x_post", "Post to X", {}, roles=["cmo"]),
        _entry("fs_write", "Write file", {}, roles=["cto"]),
    ]
    out = render_for_role("ceo", entries)
    assert "stripe_issue_card" in out
    assert "x_post" in out
    assert "fs_write" in out


def test_output_is_stable_across_calls():
    """Same inputs must produce identical output."""
    entries = [_entry("a", "a desc", {}), _entry("b", "b desc", {})]
    assert render_for_role("ceo", entries) == render_for_role("ceo", entries)


def test_empty_catalog_returns_empty_marker():
    out = render_for_role("ceo", [])
    assert "no skills" in out.lower()


def test_skill_with_no_params_renders_cleanly():
    entries = [_entry("time_now", "Returns current time", {})]
    out = render_for_role("ceo", entries)
    assert "time_now" in out
    assert "()" not in out or "time_now()" in out


def test_compact_mode_omits_descriptions_and_params():
    entries = [
        _entry("fs_write", "Write a file", {"path": "str", "content": "str"}),
        _entry("time_now", "Returns current time", {}),
    ]
    out = render_for_role("ceo", entries, compact=True)
    assert "fs_write" in out
    assert "time_now" in out
    assert "Write a file" not in out
    assert "path: str" not in out


def test_compact_mode_respects_role_filtering():
    entries = [
        _entry("stripe_issue_card", "Issue card", {}, roles=["cfo"]),
        _entry("x_post", "Post to X", {}, roles=["cmo"]),
    ]
    cfo_out = render_for_role("cfo", entries, compact=True)
    assert "stripe_issue_card" in cfo_out
    assert "x_post" not in cfo_out
