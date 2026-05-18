META = {
    "name": "screenshot_annotate", "builtin": True,
    "description": "Screenshot a URL, then draw the provided annotations (boxes/arrows/text) on it. annotations is a list of dicts like {type: 'box', xyxy: [x0,y0,x1,y1], colour: 'red'}.",
    "params": {"url": "str", "annotations": "list", "output_path": "str", "viewport": "str"},
    "returns": {"path": "str", "annotation_count": "int"},
    "cost_estimate_usd": 0.02, "timeout_s": 120.0,
}


async def run(ctx, url: str, annotations: list, output_path: str,
              viewport: str = "1280x720") -> dict:
    raw_path = f"{output_path}.raw.png"
    await ctx.media.screenshot_url(url=url, output_path=raw_path, viewport=viewport)
    result = await ctx.media.annotate_image(
        input_path=raw_path, output_path=output_path, annotations=annotations,
    )
    return {
        "path": str(result.get("path", output_path)),
        "annotation_count": int(result.get("annotation_count", 0)),
    }
