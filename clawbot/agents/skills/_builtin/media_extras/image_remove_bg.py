META = {
    "name": "image_remove_bg", "builtin": True,
    "description": "Strip the background from an image (Remove.bg or Stability inpaint). Returns the path of the cut-out PNG.",
    "params": {"image_url": "str", "output_path": "str"},
    "returns": {"path": "str", "source_url": "str"},
    "cost_estimate_usd": 0.01, "timeout_s": 120.0,
}


async def run(ctx, image_url: str, output_path: str) -> dict:
    result = await ctx.media.image_remove_bg(image_url=image_url, output_path=output_path)
    return {
        "path": str(result.get("path", output_path)),
        "source_url": str(result.get("source_url", image_url)),
    }
