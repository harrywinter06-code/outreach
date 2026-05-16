"""Shared JSON extraction utility used by scheduler and directive_router."""
import json
import re


def extract_json(text: str) -> dict:
    """Return the first JSON object in text, stripping markdown fences if present.

    Raises ValueError if no JSON object is found or it fails to parse.
    """
    match = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
    blob = match.group(1) if match else text
    start = blob.find("{")
    end = blob.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object found in text")
    return json.loads(blob[start: end + 1])
