META = {
    "name": "image_upscale", "builtin": True,
    "description": "Upscale an image NxN via Stability AI's fast-upscale endpoint. Returns the path of the larger PNG.",
    "params": {"image_url": "str", "output_path": "str", "scale": "int"},
    "returns": {"path": "str", "scale": "int"},
    "cost_estimate_usd": 0.005, "timeout_s": 120.0,
}


async def run(ctx, image_url: str, output_path: str, scale: int = 2) -> dict:
    result = await ctx.media.image_upscale(
        image_url=image_url, output_path=output_path, scale=scale,
    )
    return {
        "path": str(result.get("path", output_path)),
        "scale": int(result.get("scale", scale)),
    }
