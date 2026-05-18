META = {
    "name": "rss_publish", "builtin": True,
    "description": "Append an item to data/feeds/main.xml. Creates the feed if missing. Pure stdlib XML string manipulation.",
    "params": {"title": "str", "link": "str", "description": "str"},
    "returns": {"feed_path": "str", "items_total": "int"},
}


async def run(ctx, title: str, link: str, description: str) -> dict:
    import re as _re
    feed_path = "data/feeds/main.xml"
    existing = ""
    try:
        existing = await ctx.fs.read(feed_path)
    except Exception:
        existing = ""
    if "<channel>" not in existing:
        existing = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<rss version="2.0">\n'
            '<channel>\n'
            '<title>Clawbot</title>\n'
            '<link>https://clawbot.local/</link>\n'
            '<description>Clawbot feed</description>\n'
            '</channel>\n'
            '</rss>\n'
        )
    pub_date = ctx.time.now_iso()
    item_xml = (
        f"<item>"
        f"<title>{_escape(title)}</title>"
        f"<link>{_escape(link)}</link>"
        f"<description>{_escape(description)}</description>"
        f"<pubDate>{pub_date}</pubDate>"
        f"</item>\n"
    )
    updated = existing.replace("</channel>", f"{item_xml}</channel>", 1)
    await ctx.fs.write(feed_path, updated)
    return {"feed_path": feed_path,
            "items_total": len(_re.findall(r"<item\b", updated))}


def _escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;").replace("'", "&apos;"))
