META = {
    "name": "video_dub", "builtin": True,
    "description": "Dub a video into a target language via ElevenLabs. Returns the dubbed video URL or dubbing job id.",
    "params": {"video_path": "str", "target_lang": "str"},
    "returns": {"url": "str", "target_lang": "str"},
    "cost_estimate_usd": 0.2, "timeout_s": 300.0, "requires_approval": True,
}


async def run(ctx, video_path: str, target_lang: str) -> dict:
    result = await ctx.media.video_dub(video_path=video_path, target_lang=target_lang)
    return {
        "url": str(result.get("url", "")),
        "target_lang": str(result.get("target_lang", target_lang)),
    }
