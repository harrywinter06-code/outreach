META = {
    "name": "favicon_generate", "builtin": True,
    "description": "Generate favicon set (16/32/48/180 px) for a brand by generating a base image then writing four sized copies.",
    "params": {"brand_name": "str", "output_dir": "str"},
    "returns": {"paths": "list", "base_url": "str"},
    "cost_estimate_usd": 0.04, "timeout_s": 180.0,
}


async def run(ctx, brand_name: str, output_dir: str = "data/favicons") -> dict:
    prompt = (
        f"A square icon for the brand '{brand_name}'. Bold, simple, recognisable at 16x16 pixels, "
        f"high-contrast palette, transparent background, no text."
    )
    base = await ctx.media.image_generate(prompt=prompt, transparent_bg=True, size="180x180")
    base_url = str(base.get("url", ""))
    sizes = [16, 32, 48, 180]
    paths: list[str] = []
    for size in sizes:
        path = f"{output_dir}/favicon-{size}.png"
        await ctx.media.image_upscale(
            image_url=base_url, output_path=path, scale=max(1, size // 16),
        )
        paths.append(path)
    return {"paths": paths, "base_url": base_url}
