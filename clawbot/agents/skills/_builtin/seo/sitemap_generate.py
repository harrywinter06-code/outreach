META = {
    "name": "sitemap_generate", "builtin": True,
    "description": "Walk data/published/*.html and emit a urlset sitemap to data/sitemap.xml. base_url becomes the URL prefix.",
    "params": {"base_url": "str", "source_dir": "str", "output_path": "str"},
    "returns": {"path": "str", "url_count": "int"},
}


async def run(ctx, base_url: str, source_dir: str = "data/published",
              output_path: str = "data/sitemap.xml") -> dict:
    base = base_url.rstrip("/")
    try:
        entries = await ctx.fs.list(source_dir)
    except Exception:
        entries = []
    urls: list[str] = []
    for entry in entries:
        name = str(entry).replace("\\", "/").rsplit("/", 1)[-1]
        if name.lower().endswith(".html"):
            slug = name[:-5]
            urls.append(f"{base}/{slug}")
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in sorted(set(urls)):
        lines.append(f"  <url><loc>{u}</loc></url>")
    lines.append("</urlset>")
    xml = "\n".join(lines)
    await ctx.fs.write(output_path, xml)
    return {"path": output_path, "url_count": len(urls)}
