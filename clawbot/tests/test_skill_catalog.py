"""Tests for skill_list builtin and SkillCatalogWriter."""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from clawbot.skill_ctx import make_noop_ctx
from clawbot.skill_registry import SkillRegistry

BUILTIN_DIR = Path(__file__).parent.parent / "agents" / "skills" / "_builtin"


# ── skill_list builtin ────────────────────────────────────────────────────────


def test_skill_list_noop_returns_empty():
    """With a noop vector (returns []), skill_list returns empty list."""
    reg = SkillRegistry(skills_dir=BUILTIN_DIR)
    reg.discover()
    ctx = make_noop_ctx(caller_id="test", budget_usd=0.0)
    record = asyncio.run(reg.call("skill_list", {}, ctx))
    assert record.ok is True
    assert record.result == {"skills": [], "count": 0}


def test_skill_list_parses_catalog_from_vector():
    """When vector.search returns a catalog memory, skill_list parses it correctly."""
    reg = SkillRegistry(skills_dir=BUILTIN_DIR)
    reg.discover()

    catalog_text = (
        "Available skills catalog\n"
        "- http_fetch: Fetch a URL via GET\n"
        "- llm_complete: Call the LLM with a prompt\n"
        "- skill_list: List every currently-registered skill\n"
    )

    mock_vector = MagicMock()
    mock_vector.search = AsyncMock(return_value=[{"text": catalog_text}])

    ctx = make_noop_ctx(caller_id="test", budget_usd=0.0)
    # Replace the frozen dataclass's vector field via object.__setattr__ workaround:
    import dataclasses
    ctx = dataclasses.replace(ctx, vector=mock_vector)

    record = asyncio.run(reg.call("skill_list", {}, ctx))
    assert record.ok is True
    assert record.result["count"] == 3
    names = [s["name"] for s in record.result["skills"]]
    assert "http_fetch" in names
    assert "llm_complete" in names
    assert "skill_list" in names
    descs = {s["name"]: s["description"] for s in record.result["skills"]}
    assert descs["http_fetch"] == "Fetch a URL via GET"


# ── SkillCatalogWriter ────────────────────────────────────────────────────────


def test_catalog_writer_writes_summary_on_change():
    """write_once() calls brain.write with text containing 'Available skills'."""
    from clawbot.skill_catalog_writer import SkillCatalogWriter

    mock_registry = MagicMock()
    mock_registry.list_names.return_value = ["http_fetch", "llm_complete"]
    mock_registry.get_meta.side_effect = lambda name: MagicMock(description=f"desc of {name}")

    mock_brain = MagicMock()
    mock_brain.write = AsyncMock(return_value="42")

    writer = SkillCatalogWriter(registry=mock_registry, brain=mock_brain)
    asyncio.run(writer.write_once())

    mock_brain.write.assert_called_once()
    call_kwargs = mock_brain.write.call_args
    # brain.write(text, kind, metadata) — positional args
    text_arg = call_kwargs.args[0] if call_kwargs.args else call_kwargs.kwargs.get("text", "")
    assert "Available skills" in text_arg
    assert "http_fetch" in text_arg
