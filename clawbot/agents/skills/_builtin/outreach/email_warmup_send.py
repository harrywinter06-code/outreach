META = {
    "name": "email_warmup_send", "builtin": True,
    "description": "Send warmup emails to allied addresses listed in data/warmup_addresses.csv to build sender reputation.",
    "params": {"count": "int"},
    "returns": {"sent": "int", "failed": "int"},
    "timeout_s": 60.0,
}


async def run(ctx, count: int = 3) -> dict:
    import re as _re
    try:
        raw = await ctx.fs.read("data/warmup_addresses.csv")
    except Exception:
        raw = ""
    addrs = [
        line.strip().split(",")[0] for line in raw.splitlines() if line.strip()
    ]
    addrs = [a for a in addrs if _re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", a)]
    sent = 0
    failed = 0
    for addr in addrs[: max(0, int(count))]:
        try:
            await ctx.email.send(
                to=addr,
                subject=f"Warmup ping {ctx.time.now_iso()[:19]}",
                body_text="Routine deliverability check — please archive.",
            )
            sent += 1
        except Exception:
            failed += 1
    return {"sent": sent, "failed": failed}
