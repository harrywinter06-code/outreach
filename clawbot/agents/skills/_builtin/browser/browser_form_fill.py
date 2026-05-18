import json

META = {
    "name": "browser_form_fill", "builtin": True,
    "description": "Visit URL, fill a form using a {field_name: value} map, submit. Returns success + page output.",
    "params": {"url": "str", "field_map": "dict", "submit": "bool"},
    "returns": {"success": "bool", "output": "str", "error": "str"},
    "cost_estimate_usd": 0.02, "timeout_s": 120.0,
}


async def run(ctx, url: str, field_map: dict, submit: bool = True) -> dict:
    fields_str = json.dumps(field_map)
    submit_verb = "Submit the form." if submit else "Do not submit — leave the form filled."
    task = (
        f"Navigate to {url}. "
        f"Locate the primary form on the page and fill it using this JSON field map "
        f"(keys are label text or input names, values are the strings to enter): {fields_str}. "
        f"{submit_verb} "
        f"Return the resulting page URL and any visible success or error message."
    )
    result = await ctx.browser.run(task=task, max_steps=20)
    return {
        "success": bool(result.get("success", False)),
        "output": str(result.get("output", "")),
        "error": str(result.get("error", "") or ""),
    }
