META = {
    "name": "podcast_generate", "builtin": True,
    "description": "Two-voice podcast: alternate lines between voice_a and voice_b, TTS each, then stitch into one MP3.",
    "params": {"lines": "list", "voice_a": "str", "voice_b": "str", "output_path": "str"},
    "returns": {"path": "str", "segment_count": "int"},
    "cost_estimate_usd": 0.05, "timeout_s": 300.0,
}


async def run(ctx, lines: list, voice_a: str = "default", voice_b: str = "default",
              output_path: str = "data/podcasts/episode.mp3") -> dict:
    segment_paths: list[str] = []
    for i, line in enumerate(lines):
        voice = voice_a if i % 2 == 0 else voice_b
        seg_path = f"{output_path}.seg{i:03d}.mp3"
        await ctx.media.tts_generate(text=str(line), voice=voice, output_path=seg_path)
        segment_paths.append(seg_path)
    stitch = await ctx.media.stitch_audio(audio_paths=segment_paths, output_path=output_path)
    return {
        "path": str(stitch.get("path", output_path)),
        "segment_count": len(segment_paths),
    }
