META = {
    "name": "browser_solve_captcha", "builtin": True,
    "description": "Submit a CAPTCHA image URL to 2Captcha, poll for solution, return the token. Caller injects into the browser form. Requires TWOCAPTCHA_API_KEY.",
    "params": {"image_url": "str", "captcha_type": "str", "poll_seconds": "int"},
    "returns": {"solution": "str", "captcha_id": "str", "solved": "bool"},
    "cost_estimate_usd": 0.003, "timeout_s": 180.0,
}


async def run(ctx, image_url: str, captcha_type: str = "image", poll_seconds: int = 90) -> dict:
    api_key = ctx.secret.get("TWOCAPTCHA_API_KEY")
    if not api_key:
        return {"solution": "", "captcha_id": "", "solved": False}

    submit = await ctx.http.post(
        f"https://2captcha.com/in.php?key={api_key}&method=base64&body={image_url}"
        f"&json=1&type={captcha_type}",
        json={},
    )
    submit_text = str(submit.get("text", ""))
    captcha_id = ""
    if '"request":"' in submit_text:
        parts = submit_text.split('"request":"', 1)[1]
        captcha_id = parts.split('"', 1)[0]
    if not captcha_id:
        return {"solution": "", "captcha_id": "", "solved": False}

    deadline_iter = max(1, poll_seconds // 5)
    for _ in range(deadline_iter):
        poll = await ctx.http.get(
            f"https://2captcha.com/res.php?key={api_key}&action=get&id={captcha_id}&json=1",
        )
        poll_text = str(poll.get("text", ""))
        if '"status":1' in poll_text and '"request":"' in poll_text:
            sol = poll_text.split('"request":"', 1)[1].split('"', 1)[0]
            return {"solution": sol, "captcha_id": captcha_id, "solved": True}
        if "ERROR" in poll_text and "CAPCHA_NOT_READY" not in poll_text:
            return {"solution": "", "captcha_id": captcha_id, "solved": False}

    return {"solution": "", "captcha_id": captcha_id, "solved": False}
