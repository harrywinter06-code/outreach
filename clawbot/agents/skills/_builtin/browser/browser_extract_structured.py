import json

META = {
    "name": "browser_extract_structured", "builtin": True,
    "description": "Browse URL and extract fields matching a typed schema. Returns the extracted dict and a parse_ok flag.",
    "params": {"url": "str", "schema": "dict"},
    "returns": {"data": "dict", "parse_ok": "bool", "raw_output": "str"},
    "cost_estimate_usd": 0.03, "timeout_s": 120.0,
}


async def run(ctx, url: str, schema: dict) -> dict:
    schema_str = json.dumps(schema)
    task = (
        f"Visit {url}. Extract the following fields from the page content. "
        f"Schema (field_name -> expected type): {schema_str}. "
        f"Return ONLY a single JSON object on one line, no prose, no markdown fences. "
        f"Missing fields should be set to null."
    )
    result = await ctx.browser.run(task=task, max_steps=15)
    raw = str(result.get("output", ""))
    data: dict = {}
    parse_ok = False
    if result.get("success") and raw:
        try:
            parsed = json.loads(raw.strip())
            if isinstance(parsed, dict):
                data = parsed
                parse_ok = True
        except (ValueError, json.JSONDecodeError):
            parse_ok = False
    return {"data": data, "parse_ok": parse_ok, "raw_output": raw}
