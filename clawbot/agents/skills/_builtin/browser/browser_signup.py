import json

META = {
    "name": "browser_signup", "builtin": True,
    "description": "Generic signup-form handler. Drives a real browser to register with the given credentials. Returns success and the post-signup URL.",
    "params": {"url": "str", "email": "str", "password": "str", "extra_fields": "dict"},
    "returns": {"success": "bool", "output": "str", "error": "str"},
    "cost_estimate_usd": 0.02, "timeout_s": 180.0,
}


async def run(ctx, url: str, email: str, password: str, extra_fields: dict | None = None) -> dict:
    extras_str = json.dumps(extra_fields or {})
    task = (
        f"Sign up for the service at {url}. "
        f"Use email '{email}' and password '{password}'. "
        f"Fill any additional required fields from this JSON: {extras_str}. "
        f"Submit the signup form and wait for the confirmation page. "
        f"Return the final URL and any visible confirmation text."
    )
    result = await ctx.browser.run(task=task, max_steps=30)
    return {
        "success": bool(result.get("success", False)),
        "output": str(result.get("output", "")),
        "error": str(result.get("error", "") or ""),
    }
