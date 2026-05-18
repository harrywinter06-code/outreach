import hashlib

META = {
    "name": "web_diff_page", "builtin": True,
    "description": "Diff a page's current content against the last stored snapshot. Returns added/removed lines.",
    "params": {"url": "str"},
    "returns": {"added": "list", "removed": "list", "is_first_seen": "bool"},
}


async def run(ctx, url: str) -> dict:
    h = hashlib.sha256(url.encode()).hexdigest()[:16]
    snap_path = f"data/page_snapshots/{h}.html"
    resp = await ctx.http.get(url)
    new_text = str(resp.get("text", ""))
    try:
        old_text = await ctx.fs.read(snap_path)
        is_first = False
    except Exception:
        old_text = ""
        is_first = True
    old_lines = set(old_text.splitlines())
    new_lines = set(new_text.splitlines())
    await ctx.fs.write(snap_path, new_text)
    return {
        "added": sorted(new_lines - old_lines)[:50],
        "removed": sorted(old_lines - new_lines)[:50],
        "is_first_seen": is_first,
    }
