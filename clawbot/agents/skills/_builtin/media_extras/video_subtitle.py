META = {
    "name": "video_subtitle", "builtin": True,
    "description": "Generate an SRT subtitle track for a video using Whisper. Returns the SRT text.",
    "params": {"video_path": "str"},
    "returns": {"srt": "str", "video_path": "str"},
    "cost_estimate_usd": 0.01, "timeout_s": 240.0,
}


async def run(ctx, video_path: str) -> dict:
    result = await ctx.media.video_subtitle(video_path=video_path)
    return {
        "srt": str(result.get("srt", "")),
        "video_path": str(result.get("video_path", video_path)),
    }
