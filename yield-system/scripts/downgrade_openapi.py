"""Downgrade FastAPI's OpenAPI 3.1.0 output to 3.0.2 for RapidAPI import.

RapidAPI accepts 2.0, 3.0.0, 3.0.1, 3.0.2 — not 3.1.0.
The main incompatibility is nullable types: 3.1 uses anyOf+null,
3.0 uses nullable:true.

Usage: python scripts/downgrade_openapi.py
Output: docs/openapi_3_0_2.json
"""
import json
from pathlib import Path


def _fix_nullable(obj: object) -> object:
    """Recursively convert 3.1 anyOf+null to 3.0 nullable:true."""
    if isinstance(obj, dict):
        any_of = obj.get("anyOf")
        if isinstance(any_of, list):
            non_null = [s for s in any_of if s != {"type": "null"}]
            has_null = len(non_null) < len(any_of)
            if has_null and len(non_null) == 1 and isinstance(non_null[0], dict) and "type" in non_null[0]:
                result = {k: v for k, v in obj.items() if k != "anyOf"}
                result["type"] = non_null[0]["type"]
                result["nullable"] = True
                return _fix_nullable(result)
        return {k: _fix_nullable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_fix_nullable(item) for item in obj]
    return obj


def _downgrade(spec: dict) -> dict:
    result = _fix_nullable(spec)
    assert isinstance(result, dict)
    result["openapi"] = "3.0.2"
    return result


def main() -> None:
    src = Path("docs/openapi.json")
    dst = Path("docs/openapi_3_0_2.json")

    if not src.exists():
        print(f"ERROR: {src} not found. Run from the yield-system directory.")
        raise SystemExit(1)

    with src.open() as f:
        spec = json.load(f)

    result = _downgrade(spec)

    with dst.open("w") as f:
        json.dump(result, f, indent=2)

    print(f"Written {dst}")
    print("Validate at https://editor.swagger.io before uploading to RapidAPI.")


if __name__ == "__main__":
    main()
