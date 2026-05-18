META = {
    "name": "video_generate", "builtin": True,
    "description": "Generate a short video clip from a text prompt (Runway / Pika). Returns URL of the rendered MP4.",
    "params": {"prompt": "str", "duration_s": "float"},
    "returns": {"url": "str", "duration_s": "float"},
    "cost_estimate_usd": 0.5, "timeout_s": 300.0, "requires_approval": True,
}


async def run(ctx, prompt: str, duration_s: float = 4.0) -> dict:
    result = await ctx.media.video_generate(prompt=prompt, duration_s=duration_s)
    return {
        "url": str(result.get("url", "")),
        "duration_s": float(result.get("duration_s", duration_s)),
    }
