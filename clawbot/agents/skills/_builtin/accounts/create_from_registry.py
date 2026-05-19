"""Z4 — sign the agent up for a known service from the registry.

Wraps `ctx.accounts.create_account` with the service's signup_url and
quirk-specific browser-use instructions, looked up via `ctx.services`.
Agents call:

    account_create_from_registry(service_key="bluesky")

…and the registry handles all the per-service knowledge. Returns the
status from _LiveAccounts (live / zombie / skipped).
"""

META = {
    "name": "account_create_from_registry",
    "builtin": True,
    "description": "Sign up for a known service (bluesky, mastodon_uk, devto, hashnode) using the curated registry. Auto-creates email alias, drives browser-use signup, polls IMAP for verification, stores credentials in vault.",
    "params": {"service_key": "str"},
    "returns": {
        "ok": "bool",
        "status": "str",
        "service": "str",
        "email": "str",
        "reason": "str",
    },
    "cost_estimate_usd": 0.05,
    "timeout_s": 240.0,
    "requires_approval": False,
}


async def run(ctx, service_key: str) -> dict:
    spec = ctx.services.get(service_key)
    if spec is None:
        return {"ok": False, "status": "unknown_service",
                "service": service_key, "email": "",
                "reason": f"no registry entry for {service_key!r}"}

    if spec.get("requires_captcha") or spec.get("requires_phone"):
        return {"ok": False, "status": "skipped",
                "service": service_key, "email": "",
                "reason": "requires captcha/phone (no budget)"}

    notes = f"{spec.get('notes', '')} | extra: {spec.get('signup_task_extra', '')}"[:500]
    try:
        result = await ctx.accounts.create_account(
            service=spec["key"],
            signup_url=spec["signup_url"],
            notes=notes,
        )
    except Exception as exc:
        return {"ok": False, "status": "error",
                "service": service_key, "email": "",
                "reason": f"create_account raised: {exc!r}"}

    status = str(result.get("status", "unknown")).lower()
    email = str(result.get("email", ""))
    reason = str(result.get("reason", "") or "")
    is_ok = status == "live"
    return {
        "ok": is_ok,
        "status": status,
        "service": spec["key"],
        "email": email,
        "reason": reason or ("signup completed" if is_ok else "signup non-live"),
    }
