META = {
    "name": "substack_publish", "builtin": True,
    "description": "Publish a post to the configured Substack via browser-use. Requires SUBSTACK_EMAIL/PASSWORD/PUBLICATION_URL. 60-180s.",
    "params": {"title": "str", "subtitle": "str", "body_markdown": "str"},
    "returns": {"ok": "bool", "url": "str"},
    "timeout_s": 240.0,
    "requires_approval": True,
}


async def run(ctx, title: str, subtitle: str, body_markdown: str) -> dict:
    email = ctx.secret.get("SUBSTACK_EMAIL")
    password = ctx.secret.get("SUBSTACK_PASSWORD")
    publication = ctx.secret.get("SUBSTACK_PUBLICATION_URL")
    if not (email and password and publication):
        return {"ok": False, "url": ""}
    task = (
        f"Go to {publication}/publish/post?type=newsletter. Log in with email "
        f"{email} and password {password}. Set the title to: {title}. Set the "
        f"subtitle to: {subtitle}. Paste this body markdown:\n\n"
        f"{body_markdown[:8000]}\n\nClick Publish, then Send to All. "
        f"Wait for the post URL and return it as the output."
    )
    result = await ctx.browser.run(task=task, max_steps=40)
    return {
        "ok": bool(result.get("success", False)),
        "url": str(result.get("output", "")),
    }
