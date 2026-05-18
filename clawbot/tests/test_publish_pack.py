"""Publishing pack: discovery + smoke tests for the pure-fs and bus skills."""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

from clawbot.skill_registry import SkillRegistry
from clawbot.skill_ctx import make_noop_ctx

PUBLISH_DIR = Path(__file__).parent.parent / "agents" / "skills" / "_builtin" / "publish"


def _registry() -> SkillRegistry:
    reg = SkillRegistry(skills_dir=PUBLISH_DIR)
    reg.discover()
    return reg


def test_publish_pack_loads():
    reg = _registry()
    names = set(reg.list_names())
    expected = {
        "substack_publish", "medium_publish", "dev_to_publish", "hashnode_publish",
        "bluesky_post", "mastodon_post", "rss_publish", "buffer_schedule",
        "newsletter_send", "youtube_upload",
    }
    missing = expected - names
    assert not missing, f"missing publish skills: {missing}"


def test_rss_publish_creates_feed_when_missing():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    captured: dict = {}

    async def fake_read(path: str) -> str:
        raise FileNotFoundError(path)

    async def fake_write(path: str, content: str) -> None:
        captured["path"] = path
        captured["content"] = content

    ctx.fs.read = fake_read  # type: ignore[method-assign]
    ctx.fs.write = fake_write  # type: ignore[method-assign]
    record = asyncio.run(reg.call("rss_publish", {
        "title": "Post One", "link": "https://x/p1", "description": "first",
    }, ctx))
    assert record.ok, record.error
    assert record.result["items_total"] == 1
    assert "<item>" in captured["content"]
    assert "Post One" in captured["content"]


def test_rss_publish_appends_to_existing_feed():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    existing = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0"><channel><title>Clawbot</title>'
        '<item><title>One</title><link>a</link><description>x</description><pubDate>p</pubDate></item>'
        '</channel></rss>'
    )
    captured: dict = {}
    async def fake_read(path: str) -> str:
        return existing
    async def fake_write(path: str, content: str) -> None:
        captured["content"] = content
    ctx.fs.read = fake_read  # type: ignore[method-assign]
    ctx.fs.write = fake_write  # type: ignore[method-assign]
    record = asyncio.run(reg.call("rss_publish", {
        "title": "Two", "link": "https://x/p2", "description": "second",
    }, ctx))
    assert record.ok, record.error
    assert record.result["items_total"] == 2
    assert captured["content"].count("<item>") == 2


def test_rss_publish_escapes_special_chars():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    captured: dict = {}
    async def fake_read(path: str) -> str:
        return ""
    async def fake_write(path: str, content: str) -> None:
        captured["content"] = content
    ctx.fs.read = fake_read  # type: ignore[method-assign]
    ctx.fs.write = fake_write  # type: ignore[method-assign]
    asyncio.run(reg.call("rss_publish", {
        "title": "AT&T <best>", "link": "x", "description": "y",
    }, ctx))
    assert "&amp;" in captured["content"]
    assert "&lt;best&gt;" in captured["content"]


def test_youtube_upload_publishes_to_bus():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="cmo", budget_usd=0)
    ctx.bus.publish = AsyncMock(return_value="msg-id")  # type: ignore[method-assign]
    record = asyncio.run(reg.call("youtube_upload", {
        "title": "vid", "description": "d", "video_path": "/tmp/v.mp4",
    }, ctx))
    assert record.ok, record.error
    topic, payload = ctx.bus.publish.call_args.args
    assert topic == "media.youtube_upload_request"
    assert payload["title"] == "vid"
    assert payload["requested_by"] == "cmo"


def test_newsletter_send_uses_subscriber_csv():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    async def fake_read(path: str) -> str:
        return "alice@example.com\nbob@example.com,Bob\nnot-an-email\n"
    ctx.fs.read = fake_read  # type: ignore[method-assign]
    ctx.email.send = AsyncMock(return_value={"id": "msg1", "ok": True})  # type: ignore[method-assign]
    record = asyncio.run(reg.call("newsletter_send", {
        "subject": "Hi", "body_text": "Hello!", "body_html": "",
    }, ctx))
    assert record.ok, record.error
    assert record.result["sent"] == 2
    assert record.result["failed"] == 0
    assert record.result["total"] == 2


def test_medium_publish_no_creds_returns_failure():
    """Z3.5: silent-degradation pattern was hallucinating success at the
    registry layer. Now an inner ok=False propagates to record.ok=False
    so the cycle runner sees a real failure and the LLM can correct."""
    reg = _registry()
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    record = asyncio.run(reg.call("medium_publish", {
        "title": "T", "body_markdown": "B",
    }, ctx))
    assert record.ok is False, "missing creds must surface as record.ok=False"
    assert "ok=False" in (record.error or "") or record.error
    assert record.result["ok"] is False


def test_bluesky_post_no_creds_returns_failure():
    """Same as medium: missing creds → record.ok=False, not silent success."""
    reg = _registry()
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    record = asyncio.run(reg.call("bluesky_post", {"text": "hi"}, ctx))
    assert record.ok is False, "missing creds must surface as record.ok=False"
    assert "ok=False" in (record.error or "") or record.error
    assert record.result["ok"] is False
