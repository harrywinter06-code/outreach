META = {
    "name": "browser_navigate_and_record", "builtin": True,
    "description": "Execute a recorded macro: a list of plain-text step instructions, in order, starting at url. Returns the final page state.",
    "params": {"url": "str", "steps": "list"},
    "returns": {"success": "bool", "output": "str", "error": "str", "step_count": "int"},
    "cost_estimate_usd": 0.05, "timeout_s": 240.0,
}


async def run(ctx, url: str, steps: list) -> dict:
    numbered = "\n".join(f"{i+1}. {str(s)}" for i, s in enumerate(steps))
    task = (
        f"Start at {url}. Execute these steps in order, one at a time:\n{numbered}\n"
        f"After the last step, return the current URL and a one-line description of the page state."
    )
    result = await ctx.browser.run(task=task, max_steps=max(len(steps) * 4, 20))
    return {
        "success": bool(result.get("success", False)),
        "output": str(result.get("output", "")),
        "error": str(result.get("error", "") or ""),
        "step_count": len(steps),
    }
