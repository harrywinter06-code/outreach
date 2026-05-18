META = {
    "name": "browser_screenshot_element", "builtin": True,
    "description": "Visit url, locate the element matching selector (CSS or text), screenshot it, save to output_path. Returns the path.",
    "params": {"url": "str", "selector": "str", "output_path": "str"},
    "returns": {"path": "str", "success": "bool", "error": "str"},
    "cost_estimate_usd": 0.02, "timeout_s": 90.0,
}


async def run(ctx, url: str, selector: str, output_path: str) -> dict:
    task = (
        f"Open {url}. Locate the element matching this selector or visible text: '{selector}'. "
        f"Take a screenshot cropped tightly to that element and save the PNG to '{output_path}'. "
        f"Report the absolute path of the file you wrote."
    )
    result = await ctx.browser.run(task=task, max_steps=10)
    return {
        "path": output_path,
        "success": bool(result.get("success", False)),
        "error": str(result.get("error", "") or ""),
    }
