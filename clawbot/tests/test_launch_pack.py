"""Builtin third-party launch pack — pack-load + representative call tests."""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

from clawbot.skill_registry import SkillRegistry
from clawbot.skill_ctx import make_noop_ctx

BUILTIN_DIR = Path(__file__).parent.parent / "agents" / "skills" / "_builtin"


def _registry() -> SkillRegistry:
    reg = SkillRegistry(skills_dir=BUILTIN_DIR)
    reg.discover()
    return reg


LAUNCH_SKILLS = {
    "producthunt_schedule", "betalist_submit", "indiehackers_post",
    "hn_show_submit", "directory_submit_g2", "directory_submit_capterra",
    "directory_submit_alternative_to", "haro_respond",
    "prnewswire_submit", "podcast_pitch",
}


def test_launch_pack_loads():
    reg = _registry()
    loaded = set(reg.list_names())
    missing = LAUNCH_SKILLS - loaded
    assert not missing, f"missing launch skills: {missing}"


def test_betalist_submit_invokes_browser():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="cmo", budget_usd=0.0)
    ctx.browser.run = AsyncMock(return_value={  # type: ignore[method-assign]
        "success": True,
        "output": "https://betalist.com/startups/clawbot",
    })
    record = asyncio.run(reg.call("betalist_submit", {
        "name": "Clawbot", "url": "https://clawbot.example",
        "description": "Autonomous agent colony.", "category": "Productivity",
        "contact_email": "ops@example.com",
    }, ctx))
    assert record.ok is True
    assert record.result["success"] is True
    assert "betalist.com" in record.result["submission_url"]


def test_haro_respond_sends_email():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="cmo", budget_usd=0.0)
    ctx.email.send = AsyncMock(return_value={"id": "msg_haro"})  # type: ignore[method-assign]
    record = asyncio.run(reg.call("haro_respond", {
        "pitch_email": "haro+abc@helpareporter.com",
        "query_id": "12345",
        "subject_line": "Re: AI agent question",
        "pitch_body": "Here's my take in 4 lines...",
        "bio": "Founder, Clawbot.",
    }, ctx))
    assert record.ok is True
    assert record.result["ok"] is True
    args, kwargs = ctx.email.send.call_args
    assert "12345" in kwargs["subject"]


def test_podcast_pitch_no_contact_returns_false():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="cmo", budget_usd=0.0)
    ctx.http.get = AsyncMock(return_value={  # type: ignore[method-assign]
        "status": 200,
        "text": "<html>About this podcast. Contact us via the form.</html>",
        "headers": {},
    })
    record = asyncio.run(reg.call("podcast_pitch", {
        "show_name": "Indie Pod", "show_url": "https://example.com",
        "guest_name": "C", "guest_bio": "bio", "topic": "topic",
    }, ctx))
    # Z3.5: inner ok=False now propagates to record.ok=False (silent
    # degradation no longer hallucinates success at the registry).
    assert record.ok is False
    assert record.result["ok"] is False
    assert record.result["contact_email"] == ""


def test_podcast_pitch_with_contact_emails():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="cmo", budget_usd=0.0)
    ctx.http.get = AsyncMock(return_value={  # type: ignore[method-assign]
        "status": 200,
        "text": "Reach us at host@example.com or noreply@example.com.",
        "headers": {},
    })
    ctx.email.send = AsyncMock(return_value={"id": "msg_pod"})  # type: ignore[method-assign]
    record = asyncio.run(reg.call("podcast_pitch", {
        "show_name": "Indie Pod", "show_url": "https://example.com",
        "guest_name": "C", "guest_bio": "bio", "topic": "topic",
    }, ctx))
    assert record.ok is True
    assert record.result["ok"] is True
    assert record.result["contact_email"] == "host@example.com"
