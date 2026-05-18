"""Per-pack load + representative-call tests for the media extras pack
   and the new ctx.media surface (noop + protocol shape)."""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from clawbot.skill_ctx import make_noop_ctx, _NoopMedia
from clawbot.shadow_ctx import make_shadow_ctx
from clawbot.skill_registry import SkillRegistry

PACK_DIR = Path(__file__).parent.parent / "agents" / "skills" / "_builtin"
EXPECTED_MEDIA_SKILLS = {
    "video_generate", "video_subtitle", "video_dub",
    "podcast_generate", "logo_generate", "favicon_generate",
    "image_remove_bg", "image_upscale", "screenshot_annotate",
}


@pytest.fixture(scope="module")
def registry() -> SkillRegistry:
    reg = SkillRegistry(skills_dir=PACK_DIR)
    reg.discover()
    return reg


def test_media_extras_pack_loads(registry: SkillRegistry) -> None:
    loaded = set(registry.list_names())
    missing = EXPECTED_MEDIA_SKILLS - loaded
    assert not missing, f"media_extras pack missing skills: {missing}"


def test_noop_media_is_default(registry: SkillRegistry) -> None:
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    assert isinstance(ctx.media, _NoopMedia)


def test_shadow_ctx_has_media(registry: SkillRegistry) -> None:
    ctx = make_shadow_ctx(caller_id="t", budget_usd=0)
    assert ctx.media is not None
    assert isinstance(ctx.media, _NoopMedia)


def test_video_generate_invokes_media(registry: SkillRegistry) -> None:
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    ctx.media.video_generate = AsyncMock(return_value={  # type: ignore[method-assign]
        "url": "https://cdn/video.mp4", "duration_s": 6.0, "prompt": "x",
    })
    record = asyncio.run(registry.call(
        "video_generate", {"prompt": "a flying cat", "duration_s": 6.0}, ctx,
    ))
    assert record.ok is True, record.error
    assert record.result["url"] == "https://cdn/video.mp4"
    assert record.result["duration_s"] == 6.0


def test_logo_generate_uses_transparent_bg(registry: SkillRegistry) -> None:
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    ctx.media.image_generate = AsyncMock(return_value={  # type: ignore[method-assign]
        "url": "https://cdn/logo.png", "prompt": "...",
    })
    record = asyncio.run(registry.call(
        "logo_generate", {"brand_name": "Acme"}, ctx,
    ))
    assert record.ok is True, record.error
    kwargs = ctx.media.image_generate.call_args.kwargs
    assert kwargs["transparent_bg"] is True
    assert "Acme" in kwargs["prompt"]


def test_podcast_generate_composes_tts_and_stitch(registry: SkillRegistry) -> None:
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    ctx.media.tts_generate = AsyncMock(return_value={  # type: ignore[method-assign]
        "path": "data/podcasts/episode.mp3.seg000.mp3", "duration_s": 1.0,
    })
    ctx.media.stitch_audio = AsyncMock(return_value={  # type: ignore[method-assign]
        "path": "data/podcasts/episode.mp3", "track_count": 3,
    })
    record = asyncio.run(registry.call(
        "podcast_generate",
        {"lines": ["Hello.", "Hi back.", "Bye."], "voice_a": "alice", "voice_b": "bob"},
        ctx,
    ))
    assert record.ok is True, record.error
    assert record.result["segment_count"] == 3
    assert ctx.media.tts_generate.call_count == 3
    ctx.media.stitch_audio.assert_called_once()


def test_screenshot_annotate_chains_calls(registry: SkillRegistry) -> None:
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    ctx.media.screenshot_url = AsyncMock(return_value={  # type: ignore[method-assign]
        "path": "out.png.raw.png", "url": "https://x.example",
    })
    ctx.media.annotate_image = AsyncMock(return_value={  # type: ignore[method-assign]
        "path": "out.png", "annotation_count": 2,
    })
    record = asyncio.run(registry.call(
        "screenshot_annotate",
        {"url": "https://x.example",
         "annotations": [{"type": "box", "xyxy": [0, 0, 10, 10]},
                         {"type": "text", "xy": [5, 5], "text": "Hi"}],
         "output_path": "out.png"},
        ctx,
    ))
    assert record.ok is True, record.error
    assert record.result["annotation_count"] == 2
    ctx.media.screenshot_url.assert_called_once()
    ctx.media.annotate_image.assert_called_once()


def test_image_upscale_passes_scale(registry: SkillRegistry) -> None:
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    ctx.media.image_upscale = AsyncMock(return_value={  # type: ignore[method-assign]
        "path": "big.png", "scale": 4,
    })
    record = asyncio.run(registry.call(
        "image_upscale",
        {"image_url": "https://x/small.png", "output_path": "big.png", "scale": 4},
        ctx,
    ))
    assert record.ok is True, record.error
    assert record.result["scale"] == 4
    kwargs = ctx.media.image_upscale.call_args.kwargs
    assert kwargs["scale"] == 4
