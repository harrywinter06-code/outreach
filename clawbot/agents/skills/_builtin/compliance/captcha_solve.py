META = {
    "name": "captcha_solve", "builtin": True,
    "description": "Solve a CAPTCHA via 2Captcha. Submit the task, poll until ready (timeout 120s). "
                   "Returns the solution token that a browser step can inject. Needs TWOCAPTCHA_API_KEY.",
    "params": {"captcha_type": "str", "site_key": "str", "page_url": "str"},
    "returns": {"token": "str", "status": "str"},
    "cost_estimate_usd": 0.003, "timeout_s": 150.0,
}


async def run(ctx, captcha_type: str, site_key: str, page_url: str) -> dict:
    import json as _json
    api_key = ctx.secret.get("TWOCAPTCHA_API_KEY")
    submit = await ctx.http.post(
        "https://2captcha.com/in.php",
        json={
            "key": api_key,
            "method": captcha_type,
            "googlekey": site_key,
            "pageurl": page_url,
            "json": 1,
        },
    )
    try:
        sd = _json.loads(submit.get("text") or "{}")
    except ValueError:
        sd = {}
    if int(sd.get("status", 0)) != 1:
        return {"token": "", "status": sd.get("request", "submit_failed")}
    captcha_id = sd.get("request")
    for _ in range(20):
        poll = await ctx.http.get(
            f"https://2captcha.com/res.php?key={api_key}"
            f"&action=get&id={captcha_id}&json=1"
        )
        try:
            pd = _json.loads(poll.get("text") or "{}")
        except ValueError:
            pd = {}
        if int(pd.get("status", 0)) == 1:
            return {"token": pd.get("request", ""), "status": "solved"}
        if pd.get("request") and pd["request"] not in ("CAPCHA_NOT_READY", "CAPTCHA_NOT_READY"):
            return {"token": "", "status": pd["request"]}
    return {"token": "", "status": "timeout"}
