"""Z4 — extract an API key / app password from a service the agent just
signed up for, and store it in the vault so publishing skills can read
it via ctx.secret.get() on subsequent cycles.

Flow:
1. Look up the service spec via ctx.services.get(service_key)
2. Find the live account for this service via ctx.accounts.list_accounts
3. Drive ctx.browser through the per-service api_key_extraction_task
4. Parse the returned JSON for credential values
5. ctx.secret.set(name, value) for each credential
6. Verify each stored value is non-empty (browser-use sometimes returns
   right-shaped-but-empty JSON when the page didn't load)
"""
import json as _json
import re as _re

META = {
    "name": "account_extract_api_key",
    "builtin": True,
    "description": "Drive browser-use through a service's API-key extraction flow using the vaulted account session, then store extracted credentials via ctx.secret.set. Service must already be signed up via account_create_from_registry.",
    "params": {"service_key": "str"},
    "returns": {
        "ok": "bool",
        "service": "str",
        "secrets_stored": "list",
        "error": "str",
    },
    "cost_estimate_usd": 0.04,
    "timeout_s": 180.0,
    "requires_approval": False,
}


async def run(ctx, service_key: str) -> dict:
    spec = ctx.services.get(service_key)
    if spec is None:
        return {"ok": False, "service": service_key, "secrets_stored": [],
                "error": f"no registry entry for {service_key!r}"}

    extraction_task = spec.get("api_key_extraction_task", "")
    if not extraction_task:
        return {"ok": False, "service": service_key, "secrets_stored": [],
                "error": "no api_key_extraction_task in registry"}

    try:
        accounts = await ctx.accounts.list_accounts(status="live")
    except Exception as exc:
        return {"ok": False, "service": service_key, "secrets_stored": [],
                "error": f"list_accounts failed: {exc}"}

    matching = [a for a in (accounts or []) if a.get("service") == spec["key"]]
    if not matching:
        return {"ok": False, "service": service_key, "secrets_stored": [],
                "error": f"no live account for {spec['key']} (run account_create_from_registry first)"}

    account_email = matching[0].get("email", "")

    task = (
        f"You are already signed in to {spec.get('display_name', spec['key'])} "
        f"as {account_email}. {extraction_task}"
    )
    try:
        browser_result = await ctx.browser.run(task=task, max_steps=20)
    except Exception as exc:
        return {"ok": False, "service": service_key, "secrets_stored": [],
                "error": f"browser.run raised: {exc!r}"}

    if not browser_result.get("success"):
        return {"ok": False, "service": service_key, "secrets_stored": [],
                "error": f"browser-use failed: {browser_result.get('error', 'unknown')}"}

    output = str(browser_result.get("output", ""))
    parsed = _extract_json_from_output(output)
    if not parsed:
        return {"ok": False, "service": service_key, "secrets_stored": [],
                "error": f"could not parse JSON from browser output (len={len(output)})"}

    stored: list = []
    try:
        key = spec["key"]
        if key == "bluesky":
            handle = account_email.split("@", 1)[0]
            ctx.secret.set("BSKY_HANDLE", handle)
            ctx.secret.set("BSKY_APP_PASSWORD", str(parsed.get("app_password", "")))
            stored = ["BSKY_HANDLE", "BSKY_APP_PASSWORD"]
        elif key == "mastodon_uk":
            ctx.secret.set("MASTODON_INSTANCE", "mastodon.uk")
            ctx.secret.set("MASTODON_ACCESS_TOKEN", str(parsed.get("access_token", "")))
            stored = ["MASTODON_INSTANCE", "MASTODON_ACCESS_TOKEN"]
        elif key == "devto":
            ctx.secret.set("DEVTO_API_KEY", str(parsed.get("api_key", "")))
            stored = ["DEVTO_API_KEY"]
        elif key == "hashnode":
            ctx.secret.set("HASHNODE_PAT", str(parsed.get("pat", "")))
            ctx.secret.set("HASHNODE_PUBLICATION_ID", str(parsed.get("publication_id", "")))
            stored = ["HASHNODE_PAT", "HASHNODE_PUBLICATION_ID"]
        else:
            return {"ok": False, "service": service_key, "secrets_stored": [],
                    "error": f"no extraction handler wired for {key}"}
    except PermissionError as exc:
        return {"ok": False, "service": service_key, "secrets_stored": stored,
                "error": f"secret not allowlisted: {exc}"}

    empty = [n for n in stored if not ctx.secret.get(n).strip()]
    if empty:
        return {"ok": False, "service": service_key, "secrets_stored": stored,
                "error": f"extracted but empty: {empty}"}

    return {"ok": True, "service": spec["key"],
            "secrets_stored": stored, "error": ""}


def _extract_json_from_output(text: str) -> dict | None:
    """Find the first JSON object in browser-use output. Tolerates prose
    wrapping and code fences."""
    if not text:
        return None
    s = _re.sub(r"```(?:json)?\s*", "", text)
    s = _re.sub(r"\s*```", "", s)
    depth = 0
    start = -1
    for i, ch in enumerate(s):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                candidate = s[start:i + 1]
                try:
                    return _json.loads(candidate)
                except _json.JSONDecodeError:
                    start = -1
                    continue
    return None
