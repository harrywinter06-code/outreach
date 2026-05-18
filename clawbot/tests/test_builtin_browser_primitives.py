"""Per-pack load + representative-call tests for the browser primitives pack."""
import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from clawbot.skill_ctx import make_noop_ctx
from clawbot.skill_registry import SkillRegistry

PACK_DIR = Path(__file__).parent.parent / "agents" / "skills" / "_builtin"
EXPECTED_BROWSER_SKILLS = {
    "browser_signup", "browser_form_fill", "browser_extract_structured",
    "browser_solve_captcha", "browser_save_session", "browser_load_session",
    "browser_navigate_and_record", "browser_screenshot_element",
}


@pytest.fixture(scope="module")
def registry() -> SkillRegistry:
    reg = SkillRegistry(skills_dir=PACK_DIR)
    reg.discover()
    return reg


def test_browser_pack_loads(registry: SkillRegistry) -> None:
    loaded = set(registry.list_names())
    missing = EXPECTED_BROWSER_SKILLS - loaded
    assert not missing, f"browser pack missing skills: {missing}"


def test_browser_signup_invokes_browser(registry: SkillRegistry) -> None:
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    ctx.browser.run = AsyncMock(return_value={  # type: ignore[method-assign]
        "success": True, "output": "registered at /welcome", "error": "", "task": "...",
    })
    record = asyncio.run(registry.call(
        "browser_signup",
        {"url": "https://example.com/signup",
         "email": "a@b.com", "password": "x", "extra_fields": {"name": "Alice"}},
        ctx,
    ))
    assert record.ok is True, record.error
    assert record.result["success"] is True
    assert "registered" in record.result["output"]
    ctx.browser.run.assert_called_once()


def test_browser_extract_structured_parses_json(registry: SkillRegistry) -> None:
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    ctx.browser.run = AsyncMock(return_value={  # type: ignore[method-assign]
        "success": True,
        "output": json.dumps({"price": 49.99, "title": "Widget"}),
        "error": "", "task": "...",
    })
    record = asyncio.run(registry.call(
        "browser_extract_structured",
        {"url": "https://shop.example/widget", "schema": {"price": "float", "title": "str"}},
        ctx,
    ))
    assert record.ok is True, record.error
    assert record.result["parse_ok"] is True
    assert record.result["data"]["title"] == "Widget"


def test_browser_extract_structured_handles_bad_json(registry: SkillRegistry) -> None:
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    ctx.browser.run = AsyncMock(return_value={  # type: ignore[method-assign]
        "success": True, "output": "this is not json", "error": "", "task": "...",
    })
    record = asyncio.run(registry.call(
        "browser_extract_structured",
        {"url": "https://x.example", "schema": {"x": "str"}},
        ctx,
    ))
    assert record.ok is True
    assert record.result["parse_ok"] is False
    assert record.result["data"] == {}


def test_browser_save_session_writes_to_fs(registry: SkillRegistry) -> None:
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    ctx.browser.run = AsyncMock(return_value={  # type: ignore[method-assign]
        "success": True, "output": '{"cookies": [{"name": "sid"}]}',
        "error": "", "task": "...",
    })
    ctx.fs.write = AsyncMock(return_value=None)  # type: ignore[method-assign]
    record = asyncio.run(registry.call(
        "browser_save_session", {"name": "gumroad-prod"}, ctx,
    ))
    assert record.ok is True, record.error
    assert record.result["saved"] is True
    assert record.result["path"] == "data/sessions/gumroad-prod.json"
    ctx.fs.write.assert_called_once()
    args, _ = ctx.fs.write.call_args
    assert args[0] == "data/sessions/gumroad-prod.json"


def test_browser_load_session_reads_state(registry: SkillRegistry) -> None:
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    ctx.fs.read = AsyncMock(return_value='{"cookies": []}')  # type: ignore[method-assign]
    ctx.browser.run = AsyncMock(return_value={  # type: ignore[method-assign]
        "success": True, "output": "logged in as alice",
        "error": "", "task": "...",
    })
    record = asyncio.run(registry.call(
        "browser_load_session",
        {"name": "gumroad-prod", "target_url": "https://gumroad.com/dashboard"},
        ctx,
    ))
    assert record.ok is True, record.error
    assert record.result["success"] is True
    ctx.fs.read.assert_called_once_with("data/sessions/gumroad-prod.json")


def test_browser_load_session_missing_file(registry: SkillRegistry) -> None:
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    ctx.fs.read = AsyncMock(side_effect=FileNotFoundError("nope"))  # type: ignore[method-assign]
    record = asyncio.run(registry.call(
        "browser_load_session",
        {"name": "nonexistent", "target_url": "https://x.example"},
        ctx,
    ))
    assert record.ok is True
    assert record.result["success"] is False
    assert "session not found" in record.result["error"]


def test_browser_solve_captcha_no_key(registry: SkillRegistry) -> None:
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    record = asyncio.run(registry.call(
        "browser_solve_captcha",
        {"image_url": "https://x/c.png", "captcha_type": "image", "poll_seconds": 5},
        ctx,
    ))
    assert record.ok is True
    assert record.result["solved"] is False
    assert record.result["solution"] == ""
