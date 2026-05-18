META = {
    "name": "logo_generate", "builtin": True,
    "description": "Generate a flat-style brand logo on a transparent background. Returns URL of the PNG.",
    "params": {"brand_name": "str", "style": "str", "palette": "str"},
    "returns": {"url": "str", "prompt": "str"},
    "cost_estimate_usd": 0.04, "timeout_s": 120.0,
}


async def run(ctx, brand_name: str, style: str = "minimal flat",
              palette: str = "monochrome") -> dict:
    prompt = (
        f"A {style} logo for the brand '{brand_name}'. "
        f"{palette} colour palette, transparent background, vector-style, no text artefacts, "
        f"centred, 1:1 aspect ratio, suitable for use on both light and dark surfaces."
    )
    result = await ctx.media.image_generate(prompt=prompt, transparent_bg=True, size="1024x1024")
    return {
        "url": str(result.get("url", "")),
        "prompt": prompt,
    }
