META = {
    "name": "browser_run", "builtin": True,
    "description": "Drive a real browser to complete a multi-step task. Returns success + output. Slow (30-120s). Use for sites with no API.",
    "params": {"task": "str", "max_steps": "int"},
    "returns": {"success": "bool", "output": "str", "error": "str"},
    "timeout_s": 180.0,
}


async def run(ctx, task: str, max_steps: int = 15) -> dict:
    return await ctx.browser.run(task=task, max_steps=max_steps)
