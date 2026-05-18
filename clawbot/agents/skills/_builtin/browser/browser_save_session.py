META = {
    "name": "browser_save_session", "builtin": True,
    "description": "Capture the current browser's storage_state (cookies + localStorage) and persist to data/sessions/<name>.json for later browser_load_session reuse.",
    "params": {"name": "str", "current_url": "str"},
    "returns": {"path": "str", "saved": "bool"},
    "cost_estimate_usd": 0.01, "timeout_s": 60.0,
}


async def run(ctx, name: str, current_url: str = "") -> dict:
    path = f"data/sessions/{name}.json"
    task = (
        f"{('Open ' + current_url + '. ') if current_url else ''}"
        f"Return the page's storage_state (cookies + localStorage) as a single JSON object on one line, "
        f"no prose, no markdown fences."
    )
    result = await ctx.browser.run(task=task, max_steps=5)
    output = str(result.get("output", "")).strip()
    if not result.get("success") or not output:
        return {"path": path, "saved": False}
    await ctx.fs.write(path, output)
    return {"path": path, "saved": True}
