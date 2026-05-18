import hashlib
import re

META = {
    "name": "news_monitor_topic", "builtin": True,
    "description": "Watch Google News RSS for a topic; return items not seen on previous calls. State is per-topic at data/news_seen/<hash>.txt.",
    "params": {"topic": "str", "max_items": "int"},
    "returns": {"new_items": "list", "total_fetched": "int"},
}


async def run(ctx, topic: str, max_items: int = 20) -> dict:
    h = hashlib.sha256(topic.encode()).hexdigest()[:16]
    state_path = f"data/news_seen/{h}.txt"
    encoded = topic.replace(" ", "+")
    resp = await ctx.http.get(
        f"https://news.google.com/rss/search?q={encoded}&hl=en-US",
    )
    text = str(resp.get("text", ""))
    items: list[dict] = []
    for m in re.finditer(
        r"<item>\s*<title>(.*?)</title>\s*<link>(.*?)</link>", text,
    ):
        items.append({"title": m.group(1).strip(), "url": m.group(2).strip()})
        if len(items) >= max_items:
            break

    try:
        seen_raw = await ctx.fs.read(state_path)
    except Exception:
        seen_raw = ""
    seen = set(seen_raw.splitlines())
    new_items = [it for it in items if it["url"] not in seen]
    if new_items:
        all_urls = list(seen | {it["url"] for it in items})
        await ctx.fs.write(state_path, "\n".join(sorted(all_urls)))
    return {"new_items": new_items, "total_fetched": len(items)}
