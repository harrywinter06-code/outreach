META = {
    "name": "browser_load_session", "builtin": True,
    "description": "Restore a saved storage_state into the browser, then navigate to target_url. Use after browser_save_session to skip login.",
    "params": {"name": "str", "target_url": "str"},
    "returns": {"success": "bool", "output": "str", "error": "str"},
    "cost_estimate_usd": 0.01, "timeout_s": 60.0,
}


async def run(ctx, name: str, target_url: str) -> dict:
    path = f"data/sessions/{name}.json"
    try:
        state = await ctx.fs.read(path)
    except Exception as exc:
        return {"success": False, "output": "", "error": f"session not found: {exc}"}
    if not state.strip():
        return {"success": False, "output": "", "error": "session file empty"}
    task = (
        f"Load the following storage_state JSON into the browser context: {state}. "
        f"Then navigate to {target_url}. Report the page title and confirm whether you appear logged-in."
    )
    result = await ctx.browser.run(task=task, max_steps=10)
    return {
        "success": bool(result.get("success", False)),
        "output": str(result.get("output", "")),
        "error": str(result.get("error", "") or ""),
    }
