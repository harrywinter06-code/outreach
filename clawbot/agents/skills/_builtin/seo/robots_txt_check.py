import re

META = {
    "name": "robots_txt_check", "builtin": True,
    "description": "Fetch /robots.txt for a domain and return its disallows, sitemaps, and per-agent rules.",
    "params": {"base_url": "str"},
    "returns": {"sitemaps": "list", "disallow": "list", "allow": "list", "status": "int"},
}


async def run(ctx, base_url: str) -> dict:
    base = base_url.rstrip("/")
    resp = await ctx.http.get(f"{base}/robots.txt")
    text = str(resp.get("text", ""))
    sitemaps: list[str] = []
    disallow: list[str] = []
    allow: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"(?i)^sitemap:\s*(\S+)", line)
        if m:
            sitemaps.append(m.group(1))
            continue
        m = re.match(r"(?i)^disallow:\s*(\S*)", line)
        if m and m.group(1):
            disallow.append(m.group(1))
            continue
        m = re.match(r"(?i)^allow:\s*(\S*)", line)
        if m and m.group(1):
            allow.append(m.group(1))
    return {
        "sitemaps": sitemaps, "disallow": disallow, "allow": allow,
        "status": int(resp.get("status", 0)),
    }
