import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock


def test_main_wires_singleton_registry():
    from clawbot import skill_registry as mod
    skills_dir = Path(__file__).parent.parent / "agents" / "skills" / "_builtin"
    mod.init_skill_system(skills_dir=skills_dir)
    assert mod.REGISTRY is not None
    assert "http_fetch" in mod.REGISTRY.list_names()
